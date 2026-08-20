"""Column-mapping wizard model: suggest, then resolve, source columns to fields.

Why this module exists
======================
plan.md §10.3 specifies a mapping step between "we read your file" and "we
validated your file": suppliers ship ``HCP ID``, ``hcp_identifier``,
``PrescriberID`` and ``doctor code`` for the same concept, and the platform
must cope without asking every tenant to rewrite their extract.

The design rule that governs everything here is **suggest, never assume**:

* An exact match on a contract field's name, title or declared alias is a fact,
  and is applied.
* Anything fuzzier is a *ranked candidate* with a score and a human-readable
  reason, offered to the user. Below :attr:`MappingThresholds.auto_apply`
  nothing is applied on the user's behalf, and two candidates that score within
  :attr:`MappingThresholds.ambiguity_margin` of each other are never separated
  by a coin toss — they raise
  :data:`~.issues.IssueCode.SCHEMA_AMBIGUOUS_COLUMN_MATCH` and stop.

This is also where the two compliance refusals fire, because they are decided
from the header alone and must happen before a single data row is parsed:

* plan.md §15 — patient identifiers and ABHA numbers
  (:data:`~.issues.IssueCode.POLICY_FORBIDDEN_PII_COLUMN`).
* plan.md §7.4 — "do not accept named target HCPs as prediction inputs"
  (:data:`~.issues.IssueCode.POLICY_NAMED_HCP_TARGETING`).

Both are **file-level errors**, not row quarantines: there is no salvageable
subset of a file that carries a column of patient phone numbers.

No persistence, no network, no DB imports (plan.md §17). A saved mapping is
plain data, so the API layer can store and replay one without this module
knowing where it lives.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Final

from speaker_roi_core.enums import DatasetType, IssueSeverity

from .contracts import DatasetContract, DType, FieldSpec, normalise_header
from .issues import Issue, IssueCode, make_issue
from .profiling import ColumnProfile, FileProfile

__all__ = [
    "DEFAULT_THRESHOLDS",
    "ColumnMapping",
    "FieldSuggestion",
    "MappingCandidate",
    "MappingSuggestion",
    "MappingThresholds",
    "resolve_mapping",
    "suggest_mapping",
]


@dataclass(frozen=True, slots=True)
class MappingThresholds:
    """Where the line sits between "applied", "offered" and "not shown"."""

    #: At or above this a candidate is applied without asking. Only an exact
    #: name/alias hit whose data shape also agrees reaches it (see
    #: :func:`_combine`), so the automatic path is genuinely unambiguous.
    auto_apply: float = 0.90
    #: Below this a candidate is not worth showing; it would be noise.
    suggest: float = 0.45
    #: Two candidates closer than this are treated as tied. Guessing between
    #: ``hcp_id`` and ``hcp_id_2`` silently is how a whole upload lands against
    #: the wrong prescriber.
    ambiguity_margin: float = 0.05
    #: Candidates retained per field for the wizard's dropdown.
    max_candidates: int = 5


DEFAULT_THRESHOLDS: Final[MappingThresholds] = MappingThresholds()


# ---------------------------------------------------------------------------
# Shape compatibility
# ---------------------------------------------------------------------------

#: How well an inferred source type supports a contract type. Asymmetric on
#: purpose:
#:
#: * ``integer`` data in a ``decimal`` field is perfect — every integer is a
#:   valid decimal.
#: * ``decimal`` data in an ``integer`` field is not: 3.5 prescriptions is a
#:   sign the column is something else.
#: * ``date`` data in a ``month`` field is fine (``2026-03-01`` is how many
#:   suppliers write a month), but ``month`` data in a ``date`` field has lost
#:   the day and is suspicious.
_SHAPE_SCORES: Final[Mapping[tuple[DType, DType], float]] = {
    (DType.INTEGER, DType.DECIMAL): 1.0,
    (DType.INTEGER, DType.BOOLEAN): 0.7,
    (DType.INTEGER, DType.STRING): 0.6,
    (DType.DECIMAL, DType.INTEGER): 0.3,
    (DType.DECIMAL, DType.STRING): 0.5,
    (DType.DATE, DType.MONTH): 0.9,
    (DType.MONTH, DType.DATE): 0.4,
    (DType.DATE, DType.STRING): 0.5,
    (DType.MONTH, DType.STRING): 0.5,
    (DType.BOOLEAN, DType.INTEGER): 0.5,
    (DType.BOOLEAN, DType.STRING): 0.5,
    (DType.CURRENCY_CODE, DType.STRING): 0.7,
    (DType.CURRENCY_CODE, DType.ENUM): 0.4,
    (DType.STRING, DType.ENUM): 0.5,
    (DType.STRING, DType.CURRENCY_CODE): 0.4,
    (DType.STRING, DType.INTEGER): 0.15,
    (DType.STRING, DType.DECIMAL): 0.15,
    (DType.STRING, DType.DATE): 0.15,
    (DType.STRING, DType.MONTH): 0.15,
    (DType.STRING, DType.BOOLEAN): 0.15,
}

#: A column with no non-null values proves nothing either way, so it scores
#: neutral rather than being punished for being empty in the sample.
_NO_EVIDENCE_SHAPE: Final[float] = 0.5


def _enum_agreement(spec: FieldSpec, profile: ColumnProfile) -> float | None:
    """Share of sampled values that are members of the field's enum.

    A far stronger signal than any name similarity: if every observed value is
    a valid :class:`~speaker_roi_core.enums.AttendanceVerificationSource`, the
    column is that field almost regardless of what its header says.
    """
    allowed = spec.allowed_values
    if not allowed:
        return None
    observed = [value for value, _ in profile.top_values]
    if not observed:
        return None
    folded = {str(item).strip().casefold() for item in allowed}
    hits = sum(1 for value in observed if value.strip().casefold() in folded)
    return hits / len(observed)


def shape_score(spec: FieldSpec, profile: ColumnProfile | None) -> tuple[float, str | None]:
    """Score how well the observed data fits ``spec``. Returns ``(score, reason)``."""
    if profile is None:
        return _NO_EVIDENCE_SHAPE, None
    if profile.is_empty:
        return _NO_EVIDENCE_SHAPE, "column is empty in the sampled rows"

    if spec.dtype is DType.ENUM:
        agreement = _enum_agreement(spec, profile)
        if agreement is not None:
            if agreement >= 0.99:
                return 1.0, "every sampled value is an allowed value for this field"
            if agreement >= 0.6:
                return 0.75, f"{agreement:.0%} of sampled values are allowed values"
            return 0.2, f"only {agreement:.0%} of sampled values are allowed values"

    if profile.inferred_dtype is spec.dtype:
        return 1.0, f"data reads as {spec.dtype}"

    score = _SHAPE_SCORES.get((profile.inferred_dtype, spec.dtype), 0.2)
    return score, f"data reads as {profile.inferred_dtype}, field expects {spec.dtype}"


# ---------------------------------------------------------------------------
# Name similarity
# ---------------------------------------------------------------------------


def _tokens(normalised: str) -> frozenset[str]:
    return frozenset(part for part in normalised.split("_") if part)


def name_score(spec: FieldSpec, normalised_header: str) -> tuple[float, str]:
    """Score header similarity to ``spec``. Returns ``(score, reason)``.

    Exact hits on the canonical name, the human title or any declared alias are
    reported as 1.0 with the matched spelling named, so the wizard can say
    *why* it chose a column rather than showing a bare number.
    """
    if not normalised_header:
        return 0.0, "header cell is blank"

    keys = spec.match_keys
    if normalised_header == keys[0]:
        return 1.0, "header equals the contract field name"
    if normalised_header in keys:
        return 1.0, f"header matches the accepted spelling '{normalised_header}'"

    best = 0.0
    reason = "no name similarity"
    header_tokens = _tokens(normalised_header)
    for key in keys:
        key_tokens = _tokens(key)
        if header_tokens and key_tokens:
            overlap = len(header_tokens & key_tokens)
            union = len(header_tokens | key_tokens)
            jaccard = overlap / union
            if jaccard > best:
                best, reason = jaccard, (f"shares {overlap} of {union} name parts with '{key}'")
            if header_tokens < key_tokens or key_tokens < header_tokens:
                # One name is a strict subset of the other ("hcp" vs "hcp_id").
                subset = 0.75
                if subset > best:
                    best, reason = subset, f"header is a shortened form of '{key}'"
        ratio = SequenceMatcher(None, normalised_header, key).ratio()
        if ratio > best:
            best, reason = ratio, f"header is {ratio:.0%} similar to '{key}'"
    return best, reason


def _combine(name: float, shape: float, *, exact: bool, has_profile: bool) -> float:
    """Fold name and shape evidence into one score.

    An exact name match starts from certainty but is *discounted by the data*:
    a column called ``month`` holding free text scores ``1.0 * (0.75 + 0.25*0.15)
    ≈ 0.79``, which sits below :attr:`MappingThresholds.auto_apply` and so gets
    offered to a human instead of applied. That is the intended behaviour —
    the name and the bytes disagreeing is exactly when a person should look.
    """
    base = 1.0 if exact else name
    if not has_profile:
        return base
    return base * (0.75 + 0.25 * shape)


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MappingCandidate:
    """One possible source column for one contract field, with its evidence."""

    field_name: str
    source_position: int
    source_header: str
    score: float
    name_score: float
    shape_score: float
    exact: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field_name,
            "source_position": self.source_position,
            "source_header": self.source_header,
            "score": round(self.score, 4),
            "name_score": round(self.name_score, 4),
            "shape_score": round(self.shape_score, 4),
            "exact": self.exact,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class FieldSuggestion:
    """Ranked candidates for a single contract field."""

    field_name: str
    required: bool
    candidates: tuple[MappingCandidate, ...]
    thresholds: MappingThresholds = DEFAULT_THRESHOLDS

    @property
    def best(self) -> MappingCandidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def is_ambiguous(self) -> bool:
        """Two candidates too close to separate without asking."""
        if len(self.candidates) < 2:
            return False
        gap = self.candidates[0].score - self.candidates[1].score
        return gap < self.thresholds.ambiguity_margin

    @property
    def auto_applicable(self) -> bool:
        best = self.best
        return (
            best is not None and best.score >= self.thresholds.auto_apply and not self.is_ambiguous
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field_name,
            "required": self.required,
            "ambiguous": self.is_ambiguous,
            "auto_applicable": self.auto_applicable,
            "candidates": [c.as_dict() for c in self.candidates],
        }


@dataclass(frozen=True, slots=True)
class MappingSuggestion:
    """Everything the wizard renders for a (contract, file) pair."""

    dataset_type: DatasetType
    contract_version: str
    suggestions: tuple[FieldSuggestion, ...]
    unmatched_columns: tuple[int, ...]
    """Source positions no field claimed, offered as "ignore" in the UI."""

    issues: tuple[Issue, ...] = ()

    def for_field(self, field_name: str) -> FieldSuggestion | None:
        for suggestion in self.suggestions:
            if suggestion.field_name == field_name:
                return suggestion
        return None

    def auto_assignments(self) -> dict[str, int]:
        """The subset safe to apply without confirmation."""
        return {
            s.field_name: s.best.source_position
            for s in self.suggestions
            if s.auto_applicable and s.best is not None
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_type": str(self.dataset_type),
            "contract_version": self.contract_version,
            "suggestions": [s.as_dict() for s in self.suggestions],
            "unmatched_columns": list(self.unmatched_columns),
            "issues": [i.as_dict() for i in self.issues],
        }


def suggest_mapping(
    contract: DatasetContract,
    header: Sequence[str],
    *,
    profile: FileProfile | None = None,
    thresholds: MappingThresholds = DEFAULT_THRESHOLDS,
) -> MappingSuggestion:
    """Rank source columns against every field of ``contract``.

    ``profile`` is optional. Without it, scoring is name-only — which is what a
    batch caller replaying a saved mapping needs. With it, the data shape either
    corroborates or undercuts the name, and an enum column can be recognised
    from its values alone.

    Assignment is greedy by descending score with a fully deterministic
    tie-break (contract field order, then source position), so the same file
    always produces the same suggestion. One source column is never assigned to
    two fields.
    """
    profiles: dict[int, ColumnProfile] = {}
    if profile is not None:
        profiles = {c.position: c for c in profile.columns}

    normalised = [normalise_header(text) for text in header]
    field_order = {spec.name: index for index, spec in enumerate(contract.fields)}

    per_field: dict[str, list[MappingCandidate]] = {}
    for spec in contract.fields:
        scored: list[MappingCandidate] = []
        for position, key in enumerate(normalised):
            if not key:
                continue
            column_profile = profiles.get(position)
            n_score, n_reason = name_score(spec, key)
            s_score, s_reason = shape_score(spec, column_profile)
            exact = n_score >= 1.0
            total = _combine(n_score, s_score, exact=exact, has_profile=column_profile is not None)
            if total < thresholds.suggest:
                continue
            reasons = [n_reason] if n_reason else []
            if s_reason:
                reasons.append(s_reason)
            scored.append(
                MappingCandidate(
                    field_name=spec.name,
                    source_position=position,
                    source_header=header[position],
                    score=total,
                    name_score=n_score,
                    shape_score=s_score,
                    exact=exact,
                    reasons=tuple(reasons),
                )
            )
        scored.sort(key=lambda c: (-c.score, c.source_position))
        per_field[spec.name] = scored[: thresholds.max_candidates]

    claimed: dict[int, str] = {}
    ranked_all = sorted(
        (c for candidates in per_field.values() for c in candidates),
        key=lambda c: (-c.score, field_order[c.field_name], c.source_position),
    )
    assigned_fields: set[str] = set()
    for candidate in ranked_all:
        if candidate.field_name in assigned_fields or candidate.source_position in claimed:
            continue
        assigned_fields.add(candidate.field_name)
        claimed[candidate.source_position] = candidate.field_name

    suggestions = tuple(
        FieldSuggestion(
            field_name=spec.name,
            required=spec.required,
            candidates=tuple(
                c
                for c in per_field[spec.name]
                if claimed.get(c.source_position, spec.name) == spec.name
            ),
            thresholds=thresholds,
        )
        for spec in contract.fields
    )
    unmatched = tuple(
        position for position, key in enumerate(normalised) if key and position not in claimed
    )
    return MappingSuggestion(
        dataset_type=contract.dataset_type,
        contract_version=contract.version,
        suggestions=suggestions,
        unmatched_columns=unmatched,
        issues=(),
    )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """The settled answer: which source position feeds which contract field.

    This is the object :mod:`.validate` consumes and the object the API layer
    persists as a reusable per-tenant mapping. It is plain data — no reader, no
    profile, no file handle — so it round-trips through JSON unchanged.
    """

    dataset_type: DatasetType
    contract_version: str
    assignments: Mapping[str, int]
    """Contract field name -> 0-based source column position."""

    ignored_positions: tuple[int, ...]
    header: tuple[str, ...]
    issues: tuple[Issue, ...] = ()
    suggestion: MappingSuggestion | None = None

    @property
    def is_fatal(self) -> bool:
        """Any :data:`~speaker_roi_core.enums.IssueSeverity.ERROR` present.

        A fatal mapping means the *file* is rejected. This is deliberately a
        different outcome from a row being quarantined: quarantine is
        recoverable per row, a fatal mapping means we never understood the file
        well enough to read a single row from it.
        """
        return any(issue.severity is IssueSeverity.ERROR for issue in self.issues)

    @property
    def mapped_fields(self) -> tuple[str, ...]:
        return tuple(sorted(self.assignments))

    def position_of(self, field_name: str) -> int | None:
        return self.assignments.get(field_name)

    def value_of(self, field_name: str, row_values: Sequence[str]) -> str | None:
        """Pull one field's raw text out of a source row, or ``None`` if unmapped."""
        position = self.assignments.get(field_name)
        if position is None or position >= len(row_values):
            return None
        return row_values[position]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_type": str(self.dataset_type),
            "contract_version": self.contract_version,
            "assignments": dict(sorted(self.assignments.items())),
            "ignored_positions": list(self.ignored_positions),
            "header": list(self.header),
            "issues": [i.as_dict() for i in self.issues],
        }


def check_forbidden_headers(
    contract: DatasetContract, header: Sequence[str], *, header_row: int = 1
) -> tuple[Issue, ...]:
    """Refuse a file whose header carries a column that must never exist.

    plan.md §15 (patient identifiers, ABHA numbers) and §7.4 (named prescriber
    targeting as a forecast input). Both produce ERROR-severity issues, checked
    against the *normalised* header so ``Patient Name``, ``patient_name`` and
    ``PATIENT NAME`` are all caught. The offending header is named — it is the
    uploader's own column label, and they cannot fix the file without knowing
    which column to remove — but no cell value is ever read.
    """
    found: list[Issue] = []
    for position, raw in enumerate(header):
        key = normalise_header(raw)
        if not key:
            continue
        for rule in contract.all_forbidden_headers:
            if rule.matches(key):
                found.append(
                    make_issue(
                        rule.code,
                        column=raw,
                        row_number=header_row,
                        pattern=rule.pattern,
                        reason=rule.reason,
                        position=position + 1,
                    )
                )
                break
    return tuple(found)


def resolve_mapping(
    contract: DatasetContract,
    header: Sequence[str],
    *,
    profile: FileProfile | None = None,
    overrides: Mapping[str, int | str] | None = None,
    thresholds: MappingThresholds = DEFAULT_THRESHOLDS,
    header_row: int = 1,
    allow_unknown_columns: bool = True,
) -> ColumnMapping:
    """Settle a header into a :class:`ColumnMapping`, reporting every objection.

    Order of operations matters and is not negotiable:

    1. **Forbidden columns first.** A file carrying patient PII or a named-HCP
       target column is refused outright before any mapping work, so the
       refusal cannot be lost behind a pile of ordinary mapping warnings.
    2. Structural header faults — blank cells, duplicate headers.
    3. Automatic assignment from unambiguous suggestions.
    4. ``overrides`` (the user's explicit wizard choices, or a saved mapping)
       applied last so a human decision always wins over a machine guess.
    5. Required fields still unmapped are reported as errors.

    ``overrides`` maps a contract field name to either a source position or a
    source header string. Naming a field the contract does not define raises
    :data:`~.issues.IssueCode.SCHEMA_MAPPING_UNKNOWN_FIELD` rather than being
    ignored — a stale saved mapping must fail loudly, not drift.
    """
    issues: list[Issue] = list(check_forbidden_headers(contract, header, header_row=header_row))

    normalised = [normalise_header(text) for text in header]
    seen: dict[str, int] = {}
    for position, key in enumerate(normalised):
        if not key:
            issues.append(
                make_issue(
                    IssueCode.SCHEMA_EMPTY_HEADER_CELL,
                    column=f"#{position + 1}",
                    row_number=header_row,
                )
            )
            continue
        if key in seen:
            issues.append(
                make_issue(
                    IssueCode.SCHEMA_DUPLICATE_COLUMN,
                    column=header[position],
                    row_number=header_row,
                )
            )
        else:
            seen[key] = position

    suggestion = suggest_mapping(contract, header, profile=profile, thresholds=thresholds)

    assignments: dict[str, int] = {}
    for field_suggestion in suggestion.suggestions:
        if field_suggestion.auto_applicable and field_suggestion.best is not None:
            assignments[field_suggestion.field_name] = field_suggestion.best.source_position
        elif field_suggestion.is_ambiguous and field_suggestion.required:
            tied = [
                c.source_header
                for c in field_suggestion.candidates
                if field_suggestion.best is not None
                and field_suggestion.best.score - c.score < thresholds.ambiguity_margin
            ]
            issues.append(
                make_issue(
                    IssueCode.SCHEMA_AMBIGUOUS_COLUMN_MATCH,
                    field_name=field_suggestion.field_name,
                    row_number=header_row,
                    field=field_suggestion.field_name,
                    allowed=", ".join(tied),
                )
            )

    if overrides:
        for field_name, target in overrides.items():
            if field_name not in contract.field_map:
                issues.append(
                    make_issue(
                        IssueCode.SCHEMA_MAPPING_UNKNOWN_FIELD,
                        field_name=field_name,
                        field=field_name,
                        dataset=str(contract.dataset_type),
                    )
                )
                continue
            position = _resolve_target(target, normalised)
            if position is None:
                issues.append(
                    make_issue(
                        IssueCode.SCHEMA_MISSING_REQUIRED_COLUMN,
                        field_name=field_name,
                        field=field_name,
                        row_number=header_row,
                    )
                )
                continue
            # A human choice displaces whatever the scorer had put there.
            for existing, taken in list(assignments.items()):
                if taken == position and existing != field_name:
                    del assignments[existing]
            assignments[field_name] = position

    for spec in contract.required_fields:
        if spec.name not in assignments:
            issues.append(
                make_issue(
                    IssueCode.SCHEMA_MISSING_REQUIRED_COLUMN,
                    field_name=spec.name,
                    field=spec.name,
                    row_number=header_row,
                )
            )

    claimed = set(assignments.values())
    ignored = tuple(
        position for position, key in enumerate(normalised) if key and position not in claimed
    )
    if allow_unknown_columns:
        for position in ignored:
            issues.append(
                make_issue(
                    IssueCode.SCHEMA_UNKNOWN_COLUMN,
                    column=header[position],
                    row_number=header_row,
                    dataset=str(contract.dataset_type),
                )
            )

    return ColumnMapping(
        dataset_type=contract.dataset_type,
        contract_version=contract.version,
        assignments=dict(sorted(assignments.items())),
        ignored_positions=ignored,
        header=tuple(header),
        issues=tuple(issues),
        suggestion=suggestion,
    )


def _resolve_target(target: int | str, normalised: Sequence[str]) -> int | None:
    """Turn an override target (position or header text) into a position."""
    if isinstance(target, int):
        return target if 0 <= target < len(normalised) else None
    key = normalise_header(target)
    for position, candidate in enumerate(normalised):
        if candidate == key:
            return position
    return None
