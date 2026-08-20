"""Column profiling over a sampled prefix of an uploaded file.

Why this module exists
======================
plan.md §10.3 requires the upload flow to show the user *what we think we read*
before anything is committed: the detected encoding and delimiter, the header
row, a preview, and — per column — the inferred type, null rate, distinct count
and a couple of example values. Two separate requirements land here.

1. **Nothing is silently committed.** :mod:`.readers` returns its encoding and
   delimiter guess with a confidence score rather than acting on it. The profile
   is the object the wizard renders so a human can confirm or override.
2. **Mapping suggestions need evidence.** :mod:`.mapping` scores a source column
   against a contract field on *name* similarity and on *shape* compatibility.
   Shape comes from here: a column whose values all parse as ``YYYY-MM`` is a
   plausible ``month``, and one with a 0.98 distinct ratio is a plausible
   identifier, whatever it happens to be called.

Profiling is deliberately read-only and side-effect free. It never writes, never
resolves references, and never touches a database (plan.md §17 keeps the
analytics package free of persistence imports).

Sampling
--------
The profile reads at most ``sample_rows`` rows and stops. A 200 000-row file
must not be parsed twice just to draw a preview, and the type of a column is
established well inside the first few hundred values. :attr:`FileProfile.truncated`
records that the sample was cut short so the UI can say "based on the first N
rows" instead of implying the whole file was inspected.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any, Final

from speaker_roi_core.enums import FileFormat

from .coercion import (
    DEFAULT_COERCION,
    ISO_4217_CODES,
    CoercionOptions,
    is_null_token,
    parse_boolean,
    parse_date,
    parse_decimal,
    parse_integer,
    parse_month,
)
from .contracts import DType, normalise_header
from .issues import Issue, IssueCode, make_issue
from .readers import (
    DEFAULT_LIMITS,
    ReaderLimits,
    ReadPlan,
    SourceRow,
    open_row_source,
)

__all__ = [
    "DEFAULT_PROFILE_OPTIONS",
    "ColumnProfile",
    "FileProfile",
    "ProfileOptions",
    "infer_dtype",
    "profile_columns",
    "profile_file",
    "profile_rows",
]


#: Distinct values are counted exactly up to this cap and reported as ">= cap"
#: beyond it. An unbounded set on a 200 000-row identifier column is pure memory
#: cost for a number nobody reads past "lots".
DISTINCT_CAP: Final[int] = 1_000

#: Longest example value echoed into a profile. Examples are shown back to the
#: uploader who supplied the file, so this is a rendering cap, not a privacy
#: control — privacy is enforced by the forbidden-header refusal in
#: :mod:`.contracts` and by redaction in :mod:`.issues`.
MAX_EXAMPLE_CHARS: Final[int] = 60


@dataclass(frozen=True, slots=True)
class ProfileOptions:
    """Knobs for how much of a file the profiler looks at."""

    #: Rows parsed before profiling stops. 500 is comfortably enough to settle a
    #: column's type while staying cheap on a large upload.
    sample_rows: int = 500
    #: Rows echoed back to the user as a literal preview table.
    preview_rows: int = 20
    #: Example values captured per column.
    example_values: int = 3
    #: Share of non-null values that must parse as a type before it is inferred.
    #: Below 1.0 so a single typo does not knock an otherwise clean integer
    #: column down to ``string`` and ruin the mapping suggestion.
    type_threshold: float = 0.95
    #: Distinct-ratio above which a column is called identifier-like.
    identifier_distinct_ratio: float = 0.90
    coercion: CoercionOptions = DEFAULT_COERCION


DEFAULT_PROFILE_OPTIONS: Final[ProfileOptions] = ProfileOptions()


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------

#: Inference order is *most specific first*. Order carries real meaning:
#:
#: * ``integer`` before ``decimal`` — every integer parses as a decimal, and
#:   reporting ``nrx`` as a decimal would suggest fractional prescriptions.
#: * ``date`` before ``month`` — ``2026-03-01`` satisfies both, and a column of
#:   full dates is a date; a genuine month column contains at least one value
#:   (``2026-03``, ``Mar-26``) that no date format accepts, which is exactly
#:   when the date test fails and the month test still passes.
#: * ``currency_code`` before ``enum``/``string`` — a three-letter ISO-4217 code
#:   is unambiguous enough to name outright.
_INFERENCE_ORDER: Final[tuple[DType, ...]] = (
    DType.BOOLEAN,
    DType.INTEGER,
    DType.DECIMAL,
    DType.DATE,
    DType.MONTH,
    DType.CURRENCY_CODE,
)


def _parses_as(dtype: DType, raw: str, options: CoercionOptions) -> bool:
    """Whether ``raw`` is readable as ``dtype`` without a coercion issue."""
    if dtype is DType.BOOLEAN:
        return parse_boolean(raw).code is None
    if dtype is DType.INTEGER:
        return parse_integer(raw).code is None
    if dtype is DType.DECIMAL:
        return parse_decimal(raw).code is None
    if dtype is DType.DATE:
        return parse_date(raw, options).code is None
    if dtype is DType.MONTH:
        return parse_month(raw, options).code is None
    if dtype is DType.CURRENCY_CODE:
        return raw.strip().upper() in ISO_4217_CODES
    return True


def _looks_numeric(raw: str) -> bool:
    return raw.strip().lstrip("+-").replace(".", "", 1).isdigit()


def infer_dtype(
    values: Sequence[str],
    *,
    options: ProfileOptions = DEFAULT_PROFILE_OPTIONS,
) -> tuple[DType, float, tuple[tuple[DType, float], ...]]:
    """Infer the most specific type that ``values`` all conform to.

    Returns ``(dtype, confidence, scores)`` where ``scores`` is every candidate
    type with the share of non-null values it accepted — the wizard shows the
    runner-up so a user can see *why* a column was called a string.

    ``values`` must already have null tokens removed. An all-null column has no
    evidence and is reported as ``string`` with zero confidence rather than
    being guessed at.
    """
    if not values:
        return DType.STRING, 0.0, ()

    total = len(values)
    scores: list[tuple[DType, float]] = []
    for dtype in _INFERENCE_ORDER:
        hits = sum(1 for raw in values if _parses_as(dtype, raw, options.coercion))
        scores.append((dtype, hits / total))

    ranked = tuple(sorted(scores, key=lambda pair: (-pair[1], _INFERENCE_ORDER.index(pair[0]))))
    for dtype, share in scores:
        if share < options.type_threshold:
            continue
        if dtype is DType.BOOLEAN and all(_looks_numeric(raw) for raw in values):
            # ``0``/``1`` parse as booleans, but a column of bare digits is far
            # more often a count than a flag. Requiring at least one written-out
            # token (true/false/yes/no/Y/N) keeps ``nrx`` from being profiled as
            # a boolean the moment a supplier sends a month of zeros and ones.
            continue
        return dtype, share, ranked
    return DType.STRING, 1.0, ranked


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    """What a single source column looks like across the sampled rows."""

    position: int
    """0-based index in the header row."""

    header: str
    """Header text exactly as it appeared in the file."""

    normalised_header: str
    """Header run through :func:`.contracts.normalise_header` for matching."""

    sampled: int
    """Rows the column was observed over (including nulls)."""

    null_count: int
    non_empty_count: int
    distinct_count: int
    distinct_capped: bool
    """``True`` when the distinct count hit :data:`DISTINCT_CAP` and is a floor."""

    inferred_dtype: DType
    dtype_confidence: float
    candidate_dtypes: tuple[tuple[DType, float], ...]
    examples: tuple[str, ...]
    min_text: str | None
    max_text: str | None
    min_length: int
    max_length: int
    top_values: tuple[tuple[str, int], ...]
    """Most frequent values, useful for confirming an enum column."""

    is_blank_header: bool = False
    is_duplicate_header: bool = False

    @property
    def null_rate(self) -> float:
        return 0.0 if self.sampled == 0 else self.null_count / self.sampled

    @property
    def distinct_ratio(self) -> float:
        if self.non_empty_count == 0:
            return 0.0
        return self.distinct_count / self.non_empty_count

    @property
    def is_constant(self) -> bool:
        return self.non_empty_count > 0 and self.distinct_count == 1

    @property
    def is_empty(self) -> bool:
        return self.non_empty_count == 0

    def looks_like_identifier(self, *, options: ProfileOptions = DEFAULT_PROFILE_OPTIONS) -> bool:
        """High-cardinality, low-null columns behave like keys."""
        return (
            self.non_empty_count >= 5
            and self.distinct_ratio >= options.identifier_distinct_ratio
            and self.null_rate <= 0.05
        )

    def looks_like_enum(self) -> bool:
        """Small, repeating vocabulary — a candidate for a controlled list."""
        return 1 < self.distinct_count <= 30 and not self.distinct_capped

    def as_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "header": self.header,
            "normalised_header": self.normalised_header,
            "sampled": self.sampled,
            "null_count": self.null_count,
            "null_rate": round(self.null_rate, 4),
            "non_empty_count": self.non_empty_count,
            "distinct_count": self.distinct_count,
            "distinct_capped": self.distinct_capped,
            "inferred_dtype": str(self.inferred_dtype),
            "dtype_confidence": round(self.dtype_confidence, 4),
            "candidate_dtypes": [
                {"dtype": str(d), "share": round(s, 4)} for d, s in self.candidate_dtypes
            ],
            "examples": list(self.examples),
            "min": self.min_text,
            "max": self.max_text,
            "min_length": self.min_length,
            "max_length": self.max_length,
            "top_values": [{"value": v, "count": c} for v, c in self.top_values],
            "is_blank_header": self.is_blank_header,
            "is_duplicate_header": self.is_duplicate_header,
        }


@dataclass(frozen=True, slots=True)
class FileProfile:
    """Everything the wizard needs to describe a file before it is validated."""

    path: Path
    plan: ReadPlan
    header: tuple[str, ...]
    header_row_number: int
    columns: tuple[ColumnProfile, ...]
    preview: tuple[SourceRow, ...]
    sampled_rows: int
    truncated: bool
    """``True`` when the file has more rows than were profiled."""

    issues: tuple[Issue, ...] = ()

    @property
    def file_format(self) -> FileFormat:
        return self.plan.file_format

    @property
    def needs_confirmation(self) -> bool:
        """Whether the reader made a guess a human should sign off on.

        plan.md §10.3: the delimiter and encoding guess is *offered*, never
        applied on the user's behalf. The upload cannot proceed to validation
        while this is ``True`` and nothing has been confirmed.
        """
        return not (self.plan.delimiter_confirmed and self.plan.encoding_confirmed)

    def column_for(self, header: str) -> ColumnProfile | None:
        """Look a column up by normalised header (first wins on duplicates)."""
        key = normalise_header(header)
        for column in self.columns:
            if column.normalised_header == key:
                return column
        return None

    def column_at(self, position: int) -> ColumnProfile | None:
        for column in self.columns:
            if column.position == position:
                return column
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path.name,
            "file_format": str(self.file_format),
            "encoding": self.plan.encoding,
            "encoding_confidence": round(self.plan.encoding_confidence, 4),
            "encoding_confirmed": self.plan.encoding_confirmed,
            "has_bom": self.plan.has_bom,
            "delimiter": self.plan.delimiter_label,
            "delimiter_confidence": round(self.plan.delimiter_confidence, 4),
            "delimiter_confirmed": self.plan.delimiter_confirmed,
            "sheet_name": self.plan.sheet_name,
            "sheet_names": list(self.plan.sheet_names),
            "hidden_sheet_names": list(self.plan.hidden_sheet_names),
            "byte_size": self.plan.byte_size,
            "header": list(self.header),
            "header_row_number": self.header_row_number,
            "sampled_rows": self.sampled_rows,
            "truncated": self.truncated,
            "needs_confirmation": self.needs_confirmation,
            "columns": [c.as_dict() for c in self.columns],
            "preview": [
                {"row_number": r.row_number, "values": list(r.values)} for r in self.preview
            ],
            "issues": [i.as_dict() for i in self.issues],
        }


# ---------------------------------------------------------------------------
# Accumulation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ColumnAccumulator:
    """Mutable running state for one column; never exposed outside this module."""

    position: int
    header: str
    sampled: int = 0
    null_count: int = 0
    values: list[str] = dc_field(default_factory=list)
    distinct: set[str] = dc_field(default_factory=set)
    distinct_capped: bool = False
    counts: Counter[str] = dc_field(default_factory=Counter)
    min_length: int = 0
    max_length: int = 0
    examples: list[str] = dc_field(default_factory=list)

    def observe(self, raw: str, *, example_budget: int) -> None:
        self.sampled += 1
        text = raw.strip()
        if is_null_token(text):
            self.null_count += 1
            return
        self.values.append(text)
        if len(self.distinct) < DISTINCT_CAP:
            self.distinct.add(text)
        elif text not in self.distinct:
            self.distinct_capped = True
        if len(self.counts) < DISTINCT_CAP:
            self.counts[text] += 1
        length = len(text)
        self.min_length = length if self.min_length == 0 else min(self.min_length, length)
        self.max_length = max(self.max_length, length)
        if len(self.examples) < example_budget and text not in self.examples:
            self.examples.append(text[:MAX_EXAMPLE_CHARS])


def _sortable(raw: str, dtype: DType, options: CoercionOptions) -> Any:
    """Typed sort key so min/max on a numeric column is numeric, not lexical."""
    if dtype is DType.INTEGER:
        return parse_integer(raw).value
    if dtype is DType.DECIMAL:
        return parse_decimal(raw).value
    if dtype is DType.DATE:
        return parse_date(raw, options).value
    if dtype is DType.MONTH:
        return parse_month(raw, options).value
    return raw


def _extremes(
    values: Sequence[str], dtype: DType, options: CoercionOptions
) -> tuple[str | None, str | None]:
    if not values:
        return None, None
    keyed: list[tuple[Any, str]] = []
    for raw in values:
        key = _sortable(raw, dtype, options)
        if key is None:
            continue
        keyed.append((key, raw))
    if not keyed:
        return None, None
    try:
        keyed.sort(key=lambda pair: pair[0])
    except TypeError:
        # Mixed comparables (a stray text value in a numeric column). Fall back
        # to lexical order rather than crashing a preview.
        keyed.sort(key=lambda pair: pair[1])
    return keyed[0][1][:MAX_EXAMPLE_CHARS], keyed[-1][1][:MAX_EXAMPLE_CHARS]


def profile_columns(
    header: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    options: ProfileOptions = DEFAULT_PROFILE_OPTIONS,
) -> tuple[tuple[ColumnProfile, ...], int]:
    """Profile in-memory rows against ``header``. Returns ``(columns, sampled)``.

    Kept free of file and reader types so it can be unit tested with literals.
    Rows shorter than the header contribute a null for the missing columns;
    rows longer are truncated. Row-shape complaints are *not* raised here —
    :mod:`.validate` owns ``SCHEMA_ROW_LENGTH_MISMATCH`` because a ragged row is
    a row-level (recoverable, quarantinable) fault, whereas everything in a
    profile is descriptive.
    """
    accumulators = [_ColumnAccumulator(position=i, header=h) for i, h in enumerate(header)]
    sampled = 0
    for values in rows:
        sampled += 1
        for index, accumulator in enumerate(accumulators):
            raw = values[index] if index < len(values) else ""
            accumulator.observe(raw, example_budget=options.example_values)

    seen: Counter[str] = Counter()
    for accumulator in accumulators:
        seen[normalise_header(accumulator.header)] += 1

    profiles: list[ColumnProfile] = []
    for accumulator in accumulators:
        normalised = normalise_header(accumulator.header)
        dtype, confidence, candidates = infer_dtype(accumulator.values, options=options)
        minimum, maximum = _extremes(accumulator.values, dtype, options.coercion)
        profiles.append(
            ColumnProfile(
                position=accumulator.position,
                header=accumulator.header,
                normalised_header=normalised,
                sampled=accumulator.sampled,
                null_count=accumulator.null_count,
                non_empty_count=len(accumulator.values),
                distinct_count=len(accumulator.distinct),
                distinct_capped=accumulator.distinct_capped,
                inferred_dtype=dtype,
                dtype_confidence=confidence,
                candidate_dtypes=candidates,
                examples=tuple(accumulator.examples),
                min_text=minimum,
                max_text=maximum,
                min_length=accumulator.min_length,
                max_length=accumulator.max_length,
                top_values=tuple(accumulator.counts.most_common(5)),
                is_blank_header=normalised == "",
                is_duplicate_header=normalised != "" and seen[normalised] > 1,
            )
        )
    return tuple(profiles), sampled


def profile_rows(
    header: Sequence[str],
    rows: Iterable[SourceRow],
    *,
    options: ProfileOptions = DEFAULT_PROFILE_OPTIONS,
) -> tuple[tuple[ColumnProfile, ...], tuple[SourceRow, ...], int, bool]:
    """Profile :class:`.readers.SourceRow` values, also capturing a preview.

    Returns ``(columns, preview, sampled, truncated)``. Consumes at most
    ``options.sample_rows`` rows and then pulls one more to learn whether the
    file continued — the sample must not claim to describe the whole file when
    it does not.
    """
    preview: list[SourceRow] = []
    collected: list[Sequence[str]] = []
    iterator: Iterator[SourceRow] = iter(rows)
    truncated = False
    for row in iterator:
        if len(collected) >= options.sample_rows:
            truncated = True
            break
        if len(preview) < options.preview_rows:
            preview.append(row)
        collected.append(row.values)
    columns, sampled = profile_columns(header, collected, options=options)
    return columns, tuple(preview), sampled, truncated


def profile_file(
    path: Path,
    *,
    limits: ReaderLimits = DEFAULT_LIMITS,
    options: ProfileOptions = DEFAULT_PROFILE_OPTIONS,
    sheet: str | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
    allow_hidden_sheets: bool = False,
) -> FileProfile:
    """Open ``path``, read a sample, and describe it.

    ``encoding`` and ``delimiter`` are the *user's confirmed* choices; passing
    them marks the corresponding guess as confirmed on the returned plan and
    clears :attr:`FileProfile.needs_confirmation`. Passing neither leaves the
    profile flagged for review, which is the point (plan.md §10.3).

    Raises :class:`.readers.ReaderError` for file-level refusals — an
    unsupported extension, a macro-enabled or encrypted workbook, an oversized
    file. Those are fatal and carry no rows, which is deliberately a different
    outcome from a row being quarantined.
    """
    with open_row_source(
        path,
        limits=limits,
        sheet=sheet,
        encoding=encoding,
        delimiter=delimiter,
        allow_hidden_sheets=allow_hidden_sheets,
    ) as source:
        columns, preview, sampled, truncated = profile_rows(
            source.header, source.iter_rows(), options=options
        )
        issues = list(source.issues)
        for column in columns:
            if column.is_blank_header:
                issues.append(
                    make_issue(
                        IssueCode.SCHEMA_EMPTY_HEADER_CELL,
                        column=_position_label(column.position),
                        row_number=source.header_row_number,
                    )
                )
            elif column.is_duplicate_header:
                issues.append(
                    make_issue(
                        IssueCode.SCHEMA_DUPLICATE_COLUMN,
                        column=column.header,
                        row_number=source.header_row_number,
                    )
                )
        return FileProfile(
            path=path,
            plan=source.plan,
            header=source.header,
            header_row_number=source.header_row_number,
            columns=columns,
            preview=preview,
            sampled_rows=sampled,
            truncated=truncated,
            issues=_dedupe_issues(issues),
        )


def _position_label(position: int) -> str:
    """1-based, spreadsheet-friendly column label for a blank header."""
    return f"#{position + 1}"


def _dedupe_issues(issues: Sequence[Issue]) -> tuple[Issue, ...]:
    """Collapse identical findings so a wide header does not spam the same note."""
    seen: dict[tuple[Any, ...], Issue] = {}
    for issue in issues:
        seen.setdefault(issue.sort_key(), issue)
    return tuple(seen.values())
