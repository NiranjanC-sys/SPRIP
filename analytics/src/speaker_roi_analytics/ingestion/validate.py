"""Orchestrator: an uploaded file plus a contract becomes a ``ValidationOutcome``.

Why this module exists
======================
Everything else in this package answers one narrow question — how to read bytes,
how to parse a date, whether a row is self-consistent. This module runs the
plan.md §10.2 gates in order and produces the single object the rest of the
platform acts on.

The gate order is not arbitrary; each gate exists to stop work that the next one
would waste or that would be unsafe to perform:

1. **Extension and limits** — refuse the file outright (:mod:`.readers`).
2. **Privacy and targeting** — refuse a header carrying patient identifiers or
   named prescriber targets *before any row is read* (:mod:`.mapping`).
3. **Header and types** — resolve columns to fields, coerce every cell.
4. **Scope assignment** — the row must sit inside the brand/campaign/event scope
   declared for this upload session.
5. **Cross-tenant fail-closed** — an identifier the tenant does not own fails the
   row rather than being resolved against someone else's data.
6. **References and taxonomy** — injected resolvers, never a DB import.
7. **Row rules** — cross-field consistency within a single row.
8. **Unique keys and duplicates** — natural-key collisions settled by the
   contract's ``duplicate_policy``.
9. **Frame rules** — questions no single row can answer (overlapping effective
   ranges, one source id resolving to two masters).

Three outcomes, never collapsed
-------------------------------
* **Error (file-level)** — the file is not loadable. A macro-enabled workbook,
  a patient-PII column, a missing required column. Nothing is committed.
* **Rejected (row-level)** — that row is not loadable but the rest of the file
  is. A malformed date, a negative amount.
* **Quarantined (row-level)** — the row is *well formed but undecidable* and a
  human must choose. Two badge scans disagreeing about the same attendee, one
  source id mapping to two masters. plan.md §10.2 is explicit that these are
  never silently resolved, and quarantine is recoverable where rejection is not.

Dependency injection
--------------------
Reference existence ("is BR-ALPHA a brand this tenant owns?") and taxonomy
membership are supplied as callables. That is what keeps this package free of
FastAPI, SQLAlchemy and any driver (plan.md §17) and lets every gate here be
tested with plain dictionaries.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from speaker_roi_core.enums import DatasetType, IssueSeverity, TaxonomyKind

from .coercion import DEFAULT_COERCION, CoercionOptions, coerce_value, is_null_token
from .contracts import (
    DatasetContract,
    FieldSpec,
    ReferenceTarget,
    RowView,
    RuleContext,
    RuleOptions,
    ScopeKind,
)
from .issues import Issue, IssueCode, make_issue
from .mapping import ColumnMapping, resolve_mapping
from .profiling import (
    DEFAULT_PROFILE_OPTIONS,
    FileProfile,
    ProfileOptions,
    profile_columns,
)
from .readers import DEFAULT_LIMITS, ReaderError, ReaderLimits, SourceRow, open_row_source
from .validators import resolve_duplicates

__all__ = [
    "ReferenceResolver",
    "RowDisposition",
    "RowResult",
    "TaxonomyResolver",
    "ValidationLimits",
    "ValidationOutcome",
    "ValidationSummary",
    "validate_file",
    "validate_rows",
]


class RowDisposition(StrEnum):
    """What happened to one data row. Ordered from best to worst outcome."""

    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_WARNING = "ACCEPTED_WITH_WARNING"
    #: Well formed but superseded by a later row under the duplicate policy.
    #: Not an error — the file is correct, this row is simply not the one kept.
    SUPERSEDED = "SUPERSEDED"
    #: Well formed but undecidable; a human must resolve it. Recoverable.
    QUARANTINED = "QUARANTINED"
    #: Not loadable. Not recoverable without fixing the source file.
    REJECTED = "REJECTED"


#: Resolves ``(target, value) -> bool``: does this code exist for this tenant?
#: Returning ``None`` means "I cannot answer", which is treated as *not checked*
#: rather than as a pass — silence must never look like approval.
ReferenceResolver = Callable[[ReferenceTarget, str], bool | None]

#: Resolves ``(kind, code) -> bool``: is this code in the tenant's taxonomy?
TaxonomyResolver = Callable[[TaxonomyKind, str], bool | None]


@dataclass(frozen=True, slots=True)
class ValidationLimits:
    """Ceilings that keep one bad upload from starving the process.

    ``max_issues`` caps the issue list, not the validation: rows keep being
    classified after the cap so the counts stay honest, but only the first N
    issues are retained for the report. A file with 200 000 broken rows produces
    an unreadable report anyway, and the user needs the first few and a total.
    """

    reader: ReaderLimits = DEFAULT_LIMITS
    max_issues: int = 5_000
    #: Rows retained in the accepted frame. ``None`` means every accepted row.
    max_accepted_rows: int | None = None
    #: Abort early once this many rows are rejected — a file this broken is
    #: almost always the wrong file or the wrong contract, and validating the
    #: remaining 190 000 rows tells the user nothing new.
    max_rejected_rows: int | None = None


DEFAULT_VALIDATION_LIMITS: Final[ValidationLimits] = ValidationLimits()


@dataclass(frozen=True, slots=True)
class RowResult:
    """The verdict on one source row, with its original file row number."""

    ordinal: int
    row_number: int
    disposition: RowDisposition
    values: Mapping[str, Any]
    issue_codes: tuple[IssueCode, ...] = ()
    sheet: str | None = None

    @property
    def is_loadable(self) -> bool:
        return self.disposition in _LOADABLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "row_number": self.row_number,
            "disposition": str(self.disposition),
            "issue_codes": [str(c) for c in self.issue_codes],
            "sheet": self.sheet,
        }


_LOADABLE: Final[frozenset[RowDisposition]] = frozenset(
    {RowDisposition.ACCEPTED, RowDisposition.ACCEPTED_WITH_WARNING}
)


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    """Deterministic counts. Two runs over the same bytes produce the same object."""

    dataset_type: DatasetType
    contract_version: str
    total_rows: int
    accepted: int
    accepted_with_warning: int
    superseded: int
    quarantined: int
    rejected: int
    error_count: int
    warning_count: int
    quarantine_count: int
    info_count: int
    issues_truncated: bool
    rows_truncated: bool

    @property
    def loadable_rows(self) -> int:
        return self.accepted + self.accepted_with_warning

    @property
    def acceptance_rate(self) -> float:
        return 0.0 if self.total_rows == 0 else self.loadable_rows / self.total_rows

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_type": str(self.dataset_type),
            "contract_version": self.contract_version,
            "total_rows": self.total_rows,
            "accepted": self.accepted,
            "accepted_with_warning": self.accepted_with_warning,
            "superseded": self.superseded,
            "quarantined": self.quarantined,
            "rejected": self.rejected,
            "loadable_rows": self.loadable_rows,
            "acceptance_rate": round(self.acceptance_rate, 4),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "quarantine_count": self.quarantine_count,
            "info_count": self.info_count,
            "issues_truncated": self.issues_truncated,
            "rows_truncated": self.rows_truncated,
        }


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """Everything the platform needs to decide what to do with an upload."""

    contract: DatasetContract
    path: Path | None
    mapping: ColumnMapping | None
    profile: FileProfile | None
    rows: tuple[RowResult, ...]
    issues: tuple[Issue, ...]
    summary: ValidationSummary
    #: Set when the *file* is unusable, as distinct from rows being unusable.
    file_error: Issue | None = None

    @property
    def is_file_level_failure(self) -> bool:
        """The file itself was refused; no row was ever classified."""
        return self.file_error is not None

    @property
    def is_loadable(self) -> bool:
        """Whether a commit may proceed.

        A file with zero loadable rows is not loadable even if nothing errored:
        committing nothing and reporting success is how a silent data outage
        starts.
        """
        return (
            not self.is_file_level_failure
            and not self.has_blocking_errors
            and self.summary.loadable_rows > 0
        )

    @property
    def has_blocking_errors(self) -> bool:
        """Any file-scope ERROR. Row-scope errors reject their row, not the file."""
        return any(
            issue.severity is IssueSeverity.ERROR and issue.row_number is None
            for issue in self.issues
        )

    @property
    def accepted_rows(self) -> tuple[RowResult, ...]:
        return tuple(row for row in self.rows if row.is_loadable)

    @property
    def quarantined_rows(self) -> tuple[RowResult, ...]:
        return tuple(row for row in self.rows if row.disposition is RowDisposition.QUARANTINED)

    @property
    def rejected_rows(self) -> tuple[RowResult, ...]:
        return tuple(row for row in self.rows if row.disposition is RowDisposition.REJECTED)

    def accepted_records(self) -> tuple[Mapping[str, Any], ...]:
        """Coerced, typed values for every loadable row, in file order.

        Deliberately a tuple of mappings and not a DataFrame: this package must
        stay importable without pandas so the API layer can validate a file
        without pulling the analytics stack into a request process.
        :func:`accepted_frame` is the opt-in bridge.
        """
        return tuple(row.values for row in self.accepted_rows)

    def accepted_frame(self) -> Any:
        """The accepted rows as a ``pandas.DataFrame``. Imports pandas lazily."""
        import pandas as pd

        records = self.accepted_records()
        if not records:
            return pd.DataFrame(columns=list(self.contract.header_row()))
        return pd.DataFrame.from_records([dict(r) for r in records])

    def issues_for_row(self, row_number: int) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.row_number == row_number)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_type": str(self.contract.dataset_type),
            "contract_version": self.contract.version,
            "path": None if self.path is None else self.path.name,
            "is_loadable": self.is_loadable,
            "is_file_level_failure": self.is_file_level_failure,
            "file_error": None if self.file_error is None else self.file_error.as_dict(),
            "summary": self.summary.as_dict(),
            "mapping": None if self.mapping is None else self.mapping.as_dict(),
            "issues": [issue.as_dict() for issue in self.issues],
            "rows": [row.as_dict() for row in self.rows],
        }


# ---------------------------------------------------------------------------
# Internal accumulator
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Collector:
    """Issue sink that caps its own size while keeping the counts exact."""

    limit: int
    issues: list[Issue] = dc_field(default_factory=list)
    truncated: bool = False
    counts: dict[IssueSeverity, int] = dc_field(default_factory=dict)

    def add(self, issue: Issue) -> None:
        self.counts[issue.severity] = self.counts.get(issue.severity, 0) + 1
        if len(self.issues) < self.limit:
            self.issues.append(issue)
        else:
            self.truncated = True

    def extend(self, issues: Iterable[Issue]) -> None:
        for issue in issues:
            self.add(issue)

    def count(self, severity: IssueSeverity) -> int:
        return self.counts.get(severity, 0)


# ---------------------------------------------------------------------------
# Field-level validation
# ---------------------------------------------------------------------------


def _validate_field(
    spec: FieldSpec,
    raw: str | None,
    *,
    row_number: int,
    sheet: str | None,
    options: CoercionOptions,
) -> tuple[Any, tuple[Issue, ...]]:
    """Coerce and range-check one cell. Returns ``(value, issues)``.

    ``redact=spec.pii`` on every issue: plan.md §10.2 forbids echoing file
    contents for personal fields, so a bad ``source_hcp_id`` reports *which*
    field and *which* rule, never the identifier itself.
    """
    issues: list[Issue] = []

    def emit(code: IssueCode, **params: object) -> None:
        issues.append(
            make_issue(
                code,
                field_name=spec.name,
                row_number=row_number,
                sheet=sheet,
                redact=spec.pii,
                **params,
            )
        )

    if raw is None:
        # The column was not mapped at all. Required-column absence is a
        # file-level fault already reported by resolve_mapping; at row level an
        # unmapped optional field is simply null.
        if spec.required and not spec.nullable:
            emit(IssueCode.VALUE_REQUIRED_MISSING, field=spec.name)
            return None, tuple(issues)
        return None, ()

    if is_null_token(raw):
        if not spec.nullable:
            emit(IssueCode.VALUE_NULL_NOT_ALLOWED, field=spec.name)
        return None, tuple(issues)

    coerced = coerce_value(spec, raw, options)
    if coerced.code is not None:
        emit(coerced.code, **dict(coerced.params))
        return None, tuple(issues)

    value = coerced.value
    if value is None:
        return None, tuple(issues)

    if spec.max_length is not None and isinstance(value, str) and len(value) > spec.max_length:
        emit(IssueCode.VALUE_TOO_LONG, field=spec.name, limit=str(spec.max_length))
        return None, tuple(issues)

    if spec.minimum is not None and _below(value, spec.minimum, spec.min_exclusive):
        code = (
            IssueCode.VALUE_NEGATIVE_NOT_ALLOWED
            if _is_zero(spec.minimum) and not spec.min_exclusive
            else IssueCode.VALUE_OUT_OF_RANGE
        )
        emit(code, field=spec.name, allowed=spec.range_text or str(spec.minimum))
        return None, tuple(issues)

    if spec.maximum is not None and _above(value, spec.maximum, spec.max_exclusive):
        emit(
            IssueCode.VALUE_OUT_OF_RANGE,
            field=spec.name,
            allowed=spec.range_text or str(spec.maximum),
        )
        return None, tuple(issues)

    return value, tuple(issues)


def _below(value: Any, bound: Any, exclusive: bool) -> bool:
    try:
        return value <= bound if exclusive else value < bound
    except TypeError:  # pragma: no cover - guarded by dtype checks upstream
        return False


def _above(value: Any, bound: Any, exclusive: bool) -> bool:
    try:
        return value >= bound if exclusive else value > bound
    except TypeError:  # pragma: no cover
        return False


def _is_zero(bound: Any) -> bool:
    try:
        return bound == 0
    except TypeError:  # pragma: no cover
        return False


# ---------------------------------------------------------------------------
# Reference, taxonomy and scope gates
# ---------------------------------------------------------------------------


def _check_references(
    contract: DatasetContract,
    values: Mapping[str, Any],
    *,
    row_number: int,
    sheet: str | None,
    resolver: ReferenceResolver | None,
) -> tuple[Issue, ...]:
    """Run the contract's declared references through the injected resolver.

    No resolver means the checks are *skipped and known to be skipped*, not
    passed. A caller that wants them enforced supplies one; a unit test supplies
    a dictionary lookup.
    """
    if resolver is None:
        return ()
    issues: list[Issue] = []
    for reference in contract.references:
        raw = values.get(reference.field_name)
        if raw is None:
            continue
        spec = contract.field_map.get(reference.field_name)
        exists = resolver(reference.target, str(raw))
        if exists is False:
            issues.append(
                make_issue(
                    reference.issue_code,
                    field_name=reference.field_name,
                    row_number=row_number,
                    sheet=sheet,
                    redact=bool(spec and spec.pii),
                    field=reference.field_name,
                    value=raw,
                )
            )
    return tuple(issues)


def _check_taxonomy(
    contract: DatasetContract,
    values: Mapping[str, Any],
    *,
    row_number: int,
    sheet: str | None,
    resolver: TaxonomyResolver | None,
) -> tuple[Issue, ...]:
    """Validate taxonomy-backed codes (region, topic, cost category, ...).

    Taxonomies are tenant-configurable (plan.md §9.2), so their membership can
    only come from outside this package.
    """
    if resolver is None:
        return ()
    issues: list[Issue] = []
    for spec in contract.fields:
        if spec.taxonomy_ref is None:
            continue
        raw = values.get(spec.name)
        if raw is None:
            continue
        if resolver(spec.taxonomy_ref, str(raw)) is False:
            issues.append(
                make_issue(
                    IssueCode.TAXONOMY_UNKNOWN_VALUE,
                    field_name=spec.name,
                    row_number=row_number,
                    sheet=sheet,
                    redact=spec.pii,
                    field=spec.name,
                    value=raw,
                    kind=spec.taxonomy_ref.value,
                )
            )
    return tuple(issues)


#: Which field carries the code for each scope kind. Upload sessions are scoped
#: (plan.md §10.2 "scope assignment"), and a row naming a different brand than
#: the session declared is a cross-scope leak, not a typo.
_SCOPE_FIELDS: Final[Mapping[ScopeKind, tuple[str, ...]]] = {
    ScopeKind.BRAND: ("brand_code",),
    ScopeKind.CAMPAIGN: ("campaign_code",),
    ScopeKind.EVENT: ("event_code",),
    ScopeKind.VENDOR: ("vendor_code",),
}


def _check_scope(
    contract: DatasetContract,
    values: Mapping[str, Any],
    *,
    row_number: int,
    sheet: str | None,
    scope: Mapping[ScopeKind, str],
) -> tuple[Issue, ...]:
    """Fail closed when a row references something outside the declared scope."""
    if not scope:
        return ()
    issues: list[Issue] = []
    for kind, declared in scope.items():
        for field_name in _SCOPE_FIELDS.get(kind, ()):
            if field_name not in contract.field_map:
                continue
            raw = values.get(field_name)
            if raw is None:
                continue
            if str(raw).strip().casefold() != declared.strip().casefold():
                issues.append(
                    make_issue(
                        IssueCode.REF_OUTSIDE_DECLARED_SCOPE,
                        field_name=field_name,
                        row_number=row_number,
                        sheet=sheet,
                        scope=kind.value,
                        target=raw,
                    )
                )
    return tuple(issues)


# ---------------------------------------------------------------------------
# Row and frame orchestration
# ---------------------------------------------------------------------------


def _worst(dispositions: Iterable[RowDisposition]) -> RowDisposition:
    order = {
        RowDisposition.ACCEPTED: 0,
        RowDisposition.ACCEPTED_WITH_WARNING: 1,
        RowDisposition.SUPERSEDED: 2,
        RowDisposition.QUARANTINED: 3,
        RowDisposition.REJECTED: 4,
    }
    return max(dispositions, key=lambda d: order[d], default=RowDisposition.ACCEPTED)


def _disposition_for(severities: Sequence[IssueSeverity]) -> RowDisposition:
    """Map the severities raised against a row to its disposition.

    ERROR rejects, QUARANTINE quarantines, WARNING accepts-with-warning. ERROR
    outranks QUARANTINE: a row that is both malformed and undecidable cannot be
    fixed by a human decision, so asking for one would waste their time.
    """
    if IssueSeverity.ERROR in severities:
        return RowDisposition.REJECTED
    if IssueSeverity.QUARANTINE in severities:
        return RowDisposition.QUARANTINED
    if IssueSeverity.WARNING in severities:
        return RowDisposition.ACCEPTED_WITH_WARNING
    return RowDisposition.ACCEPTED


def validate_rows(
    contract: DatasetContract,
    rows: Iterable[SourceRow],
    mapping: ColumnMapping,
    *,
    today: dt.date,
    limits: ValidationLimits = DEFAULT_VALIDATION_LIMITS,
    options: CoercionOptions = DEFAULT_COERCION,
    rule_options: RuleOptions | None = None,
    scope: Mapping[ScopeKind, str] | None = None,
    reference_resolver: ReferenceResolver | None = None,
    taxonomy_resolver: TaxonomyResolver | None = None,
    header_width: int | None = None,
    seed_issues: Sequence[Issue] = (),
) -> ValidationOutcome:
    """Validate already-read rows against ``contract``. The core of the pipeline.

    Separated from :func:`validate_file` so every gate can be exercised from a
    list of tuples in a unit test — no temp files, no encodings, no reader.

    ``today`` is injected rather than read from the clock: the "no future period"
    gate must be reproducible, and a test asserting a boundary cannot depend on
    when it runs.
    """
    collector = _Collector(limit=limits.max_issues)
    collector.extend(seed_issues)
    collector.extend(mapping.issues)

    context = RuleContext(
        today=today,
        options=rule_options if rule_options is not None else RuleOptions(),
        scope=dict(scope or {}),
    )
    width = header_width if header_width is not None else len(mapping.header)

    row_views: list[RowView] = []
    row_meta: list[tuple[int, str | None]] = []
    per_row_severities: list[list[IssueSeverity]] = []
    per_row_codes: list[list[IssueCode]] = []
    rows_truncated = False
    rejected_so_far = 0

    for ordinal, source in enumerate(rows):
        row_issues: list[Issue] = []

        if width and len(source.values) != width:
            # A ragged row is row-level, not file-level: the rest of the file is
            # usually fine and the user needs to know which line to fix.
            row_issues.append(
                make_issue(
                    IssueCode.SCHEMA_ROW_LENGTH_MISMATCH,
                    row_number=source.row_number,
                    sheet=source.sheet,
                    actual=len(source.values),
                    expected=width,
                )
            )

        values: dict[str, Any] = {}
        for spec in contract.fields:
            raw = mapping.value_of(spec.name, source.values)
            value, field_issues = _validate_field(
                spec,
                raw,
                row_number=source.row_number,
                sheet=source.sheet,
                options=options,
            )
            values[spec.name] = value
            row_issues.extend(field_issues)

        row_issues.extend(
            _check_scope(
                contract,
                values,
                row_number=source.row_number,
                sheet=source.sheet,
                scope=context.scope,
            )
        )
        row_issues.extend(
            _check_references(
                contract,
                values,
                row_number=source.row_number,
                sheet=source.sheet,
                resolver=reference_resolver,
            )
        )
        row_issues.extend(
            _check_taxonomy(
                contract,
                values,
                row_number=source.row_number,
                sheet=source.sheet,
                resolver=taxonomy_resolver,
            )
        )

        view = RowView(ordinal=ordinal, row_number=source.row_number, values=values)
        # Gate order (plan.md §10.2): types before rules. A cell that failed
        # coercion is None by the time the rules see it, and a rule reading that
        # None would report a second, invented problem — "nrx is blank but
        # suppression_flag is not set" on a row whose real fault is that nrx was
        # "-1". One cause, one message: the user fixes the value and re-uploads.
        row_has_error = any(issue.severity is IssueSeverity.ERROR for issue in row_issues)
        for rule in () if row_has_error else contract.row_rules:
            for violation in rule.check(view, context):
                spec = contract.field_map.get(violation.field_name or "")
                row_issues.append(
                    make_issue(
                        violation.code,
                        field_name=violation.field_name,
                        row_number=source.row_number,
                        sheet=source.sheet,
                        severity=violation.severity,
                        redact=bool(spec and spec.pii),
                        **dict(violation.params),
                    )
                )

        collector.extend(row_issues)
        severities = [issue.severity for issue in row_issues]
        row_views.append(view)
        row_meta.append((source.row_number, source.sheet))
        per_row_severities.append(severities)
        per_row_codes.append([issue.code for issue in row_issues])

        if IssueSeverity.ERROR in severities:
            rejected_so_far += 1
            if limits.max_rejected_rows is not None and rejected_so_far >= limits.max_rejected_rows:
                rows_truncated = True
                break

    dispositions = [_disposition_for(sev) for sev in per_row_severities]

    # -- duplicates -------------------------------------------------------
    # Only rows that survived field validation take part: a row whose key failed
    # to parse has no usable key, and letting it collide with a valid row would
    # reject good data on the strength of bad data.
    candidate_ordinals = [i for i, d in enumerate(dispositions) if d is not RowDisposition.REJECTED]
    candidates = [row_views[i] for i in candidate_ordinals]
    resolution = resolve_duplicates(candidates, contract, context)
    for outcome in resolution.outcomes:
        row_number, sheet = row_meta[outcome.ordinal]
        key_fields = [contract.field_map.get(name) for name in contract.natural_key]
        issue = make_issue(
            outcome.code,
            row_number=row_number,
            sheet=sheet,
            severity=outcome.severity,
            redact=any(spec is not None and spec.pii for spec in key_fields),
            **dict(outcome.params),
        )
        collector.add(issue)
        per_row_codes[outcome.ordinal].append(issue.code)
        if issue.severity is IssueSeverity.ERROR:
            dispositions[outcome.ordinal] = RowDisposition.REJECTED
        elif issue.severity is IssueSeverity.QUARANTINE:
            dispositions[outcome.ordinal] = RowDisposition.QUARANTINED
    for ordinal in resolution.dropped:
        if dispositions[ordinal] in _LOADABLE:
            dispositions[ordinal] = RowDisposition.SUPERSEDED
    for ordinal in resolution.quarantined:
        if dispositions[ordinal] is not RowDisposition.REJECTED:
            dispositions[ordinal] = RowDisposition.QUARANTINED

    # -- frame rules ------------------------------------------------------
    surviving = [
        row_views[i]
        for i, d in enumerate(dispositions)
        if d in _LOADABLE or d is RowDisposition.SUPERSEDED
    ]
    for rule in contract.frame_rules:
        for violation in rule.check(surviving, context):
            spec = contract.field_map.get(violation.field_name or "")
            for ordinal in violation.ordinals:
                row_number, sheet = row_meta[ordinal]
                issue = make_issue(
                    violation.code,
                    field_name=violation.field_name,
                    row_number=row_number,
                    sheet=sheet,
                    severity=violation.severity,
                    redact=bool(spec and spec.pii),
                    **dict(violation.params),
                )
                collector.add(issue)
                per_row_codes[ordinal].append(issue.code)
                dispositions[ordinal] = _worst(
                    (dispositions[ordinal], _disposition_for([issue.severity]))
                )
            for ordinal in violation.drop_ordinals:
                if dispositions[ordinal] in _LOADABLE:
                    dispositions[ordinal] = RowDisposition.SUPERSEDED

    results = tuple(
        RowResult(
            ordinal=ordinal,
            row_number=row_meta[ordinal][0],
            disposition=dispositions[ordinal],
            values=row_views[ordinal].values,
            issue_codes=tuple(per_row_codes[ordinal]),
            sheet=row_meta[ordinal][1],
        )
        for ordinal in range(len(row_views))
    )
    if limits.max_accepted_rows is not None:
        loadable_seen = 0
        trimmed: list[RowResult] = []
        for result in results:
            if result.is_loadable:
                loadable_seen += 1
                if loadable_seen > limits.max_accepted_rows:
                    rows_truncated = True
                    continue
            trimmed.append(result)
        results = tuple(trimmed)

    summary = ValidationSummary(
        dataset_type=contract.dataset_type,
        contract_version=contract.version,
        total_rows=len(row_views),
        accepted=sum(1 for d in dispositions if d is RowDisposition.ACCEPTED),
        accepted_with_warning=sum(
            1 for d in dispositions if d is RowDisposition.ACCEPTED_WITH_WARNING
        ),
        superseded=sum(1 for d in dispositions if d is RowDisposition.SUPERSEDED),
        quarantined=sum(1 for d in dispositions if d is RowDisposition.QUARANTINED),
        rejected=sum(1 for d in dispositions if d is RowDisposition.REJECTED),
        error_count=collector.count(IssueSeverity.ERROR),
        warning_count=collector.count(IssueSeverity.WARNING),
        quarantine_count=collector.count(IssueSeverity.QUARANTINE),
        info_count=collector.count(IssueSeverity.INFO),
        issues_truncated=collector.truncated,
        rows_truncated=rows_truncated,
    )
    return ValidationOutcome(
        contract=contract,
        path=None,
        mapping=mapping,
        profile=None,
        rows=results,
        issues=tuple(sorted(collector.issues, key=lambda i: i.sort_key())),
        summary=summary,
    )


def validate_file(
    path: Path | str,
    contract: DatasetContract,
    *,
    mapping_overrides: Mapping[str, int | str] | None = None,
    limits: ValidationLimits = DEFAULT_VALIDATION_LIMITS,
    profile_options: ProfileOptions = DEFAULT_PROFILE_OPTIONS,
    coercion: CoercionOptions = DEFAULT_COERCION,
    rule_options: RuleOptions | None = None,
    today: dt.date | None = None,
    scope: Mapping[ScopeKind, str] | None = None,
    reference_resolver: ReferenceResolver | None = None,
    taxonomy_resolver: TaxonomyResolver | None = None,
    sheet: str | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
    allow_hidden_sheets: bool = False,
) -> ValidationOutcome:
    """Read ``path`` and validate it against ``contract``.

    The whole file is streamed once. Rows are profiled as they pass through, so
    the returned :class:`~.profiling.FileProfile` describes the same read that
    produced the verdicts rather than a second, possibly different, pass.

    A file-level refusal — unsupported extension, macro-enabled or encrypted
    workbook, oversized file, a forbidden column — returns an outcome with
    :attr:`ValidationOutcome.file_error` set and no rows. It does **not** raise:
    the caller wants a report to show the uploader, not a traceback.

    ``today`` defaults to the system date only when omitted; every code path that
    cares takes it from :class:`~.contracts.RuleContext` so tests can pin it.
    """
    resolved_path = Path(path)
    effective_today = today if today is not None else dt.datetime.now(dt.UTC).date()

    try:
        source = open_row_source(
            resolved_path,
            limits=limits.reader,
            sheet=sheet,
            encoding=encoding,
            delimiter=delimiter,
            allow_hidden_sheets=allow_hidden_sheets,
        )
    except ReaderError as error:
        return _file_failure(contract, resolved_path, error.issue)

    with source:
        header = source.header
        mapping = resolve_mapping(
            contract,
            header,
            profile=None,
            overrides=mapping_overrides,
            header_row=source.header_row_number,
        )
        if mapping.is_fatal:
            # Stop before reading data. A file whose header we cannot trust —
            # or must not read at all, in the privacy case — has no rows worth
            # parsing, and parsing them would put forbidden values in memory.
            blocking = next(
                (i for i in mapping.issues if i.severity is IssueSeverity.ERROR),
                None,
            )
            return _file_failure(
                contract,
                resolved_path,
                blocking,
                mapping=mapping,
                extra_issues=mapping.issues,
            )

        collected: list[SourceRow] = []
        sample: list[Sequence[str]] = []
        try:
            for row in source.iter_rows():
                collected.append(row)
                if len(sample) < profile_options.sample_rows:
                    sample.append(row.values)
        except ReaderError as error:
            return _file_failure(contract, resolved_path, error.issue, mapping=mapping)

        columns, sampled = profile_columns(header, sample, options=profile_options)
        profile = FileProfile(
            path=resolved_path,
            plan=source.plan,
            header=header,
            header_row_number=source.header_row_number,
            columns=columns,
            preview=tuple(collected[: profile_options.preview_rows]),
            sampled_rows=sampled,
            truncated=len(collected) > sampled,
            issues=source.issues,
        )

        outcome = validate_rows(
            contract,
            collected,
            mapping,
            today=effective_today,
            limits=limits,
            options=coercion,
            rule_options=rule_options,
            scope=scope,
            reference_resolver=reference_resolver,
            taxonomy_resolver=taxonomy_resolver,
            header_width=len(header),
            seed_issues=source.issues,
        )

    return ValidationOutcome(
        contract=outcome.contract,
        path=resolved_path,
        mapping=outcome.mapping,
        profile=profile,
        rows=outcome.rows,
        issues=outcome.issues,
        summary=outcome.summary,
        file_error=None,
    )


def _file_failure(
    contract: DatasetContract,
    path: Path,
    issue: Issue | None,
    *,
    mapping: ColumnMapping | None = None,
    extra_issues: Sequence[Issue] = (),
) -> ValidationOutcome:
    """Build the zero-row outcome for a file the platform refuses to read."""
    issues = list(extra_issues)
    if issue is not None and issue not in issues:
        issues.insert(0, issue)
    counts: dict[IssueSeverity, int] = {}
    for item in issues:
        counts[item.severity] = counts.get(item.severity, 0) + 1
    summary = ValidationSummary(
        dataset_type=contract.dataset_type,
        contract_version=contract.version,
        total_rows=0,
        accepted=0,
        accepted_with_warning=0,
        superseded=0,
        quarantined=0,
        rejected=0,
        error_count=counts.get(IssueSeverity.ERROR, 0),
        warning_count=counts.get(IssueSeverity.WARNING, 0),
        quarantine_count=counts.get(IssueSeverity.QUARANTINE, 0),
        info_count=counts.get(IssueSeverity.INFO, 0),
        issues_truncated=False,
        rows_truncated=False,
    )
    return ValidationOutcome(
        contract=contract,
        path=path,
        mapping=mapping,
        profile=None,
        rows=(),
        issues=tuple(sorted(issues, key=lambda i: i.sort_key())),
        summary=summary,
        file_error=issue,
    )
