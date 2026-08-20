"""Reusable row-level and frame-level validation rules.

Every rule in this module is a *builder*: it takes the field names it should
operate on and returns a :class:`~speaker_roi_analytics.ingestion.contracts.RowRule`
or :class:`~speaker_roi_analytics.ingestion.contracts.FrameRule`.  The dataset
definitions under ``definitions/`` then compose contracts out of these builders,
so a rule such as "half-open effective ranges must not overlap" is written once
and cited by every dataset that needs it.

Why builders rather than free functions the orchestrator hard-codes:

* The rule set becomes *data*.  ``contract.row_rules`` and
  ``contract.frame_rules`` are serialisable, which is what lets
  ``templates.py`` publish the rule descriptions into the data dictionary and
  the generated JSON Schema without a second, hand-maintained copy of the
  prose.  A rule that exists but is undocumented is a support ticket.
* Gate coverage becomes testable.  Each rule names an
  :class:`~speaker_roi_analytics.ingestion.issues.IssueCode`, each issue code
  names a :class:`~speaker_roi_analytics.ingestion.issues.Gate`, so
  ``tests/unit/test_ingestion_validation.py`` can assert every gate in
  plan.md §10.2 is reachable from at least one contract.

Rules run **after** coercion, so ``RowView.values`` holds native Python objects
(``Decimal``, ``date``, ``bool``, ``str``) or ``None`` — never raw strings.  A
rule must never raise: a field it depends on may be ``None`` because an earlier
gate already rejected it, and the row still has to reach the error report with
every independent problem listed rather than only the first.

No FastAPI, SQLAlchemy or database import appears here or anywhere else in this
package (plan.md §17): the analytics tier is unit-testable with plain dicts.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from speaker_roi_analytics.ingestion.contracts import (
    DatasetContract,
    FrameRule,
    FrameViolation,
    RowRule,
    RowView,
    RuleContext,
    RuleViolation,
)
from speaker_roi_analytics.ingestion.issues import IssueCode
from speaker_roi_core.enums import (
    AttendanceVerificationSource,
    IssueSeverity,
)

__all__ = [
    "DuplicateOutcome",
    "DuplicateResolution",
    "approval_requires_approver",
    "at_least_one_of",
    "attendance_status_consistent",
    "coverage_factor_sufficient",
    "date_order",
    "dependent_field_required",
    "distinguish_missing_from_zero",
    "effective_range_half_open",
    "no_future_period",
    "no_overlapping_effective_ranges",
    "resolve_duplicates",
    "single_currency_per_group",
    "suppression_consistent",
    "trx_not_below_nrx",
    "unambiguous_crosswalk",
    "verified_requires_strong_source",
]

_NO_VIOLATIONS: Final[tuple[RuleViolation, ...]] = ()
_NO_FRAME_VIOLATIONS: Final[tuple[FrameViolation, ...]] = ()


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _is_blank(value: Any) -> bool:
    """True when a coerced value carries no information.

    Empty strings survive coercion for ``string`` fields, so ``None`` alone is
    not a sufficient test for "the supplier left this out".
    """
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def _as_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return None


def _as_decimal(value: Any) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    return None


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _group_key(row: RowView, fields: Sequence[str]) -> tuple[str, ...]:
    """Case-folded grouping key.

    Supplier files routinely disagree with themselves on the casing of a code
    (``BRD-ALPHA`` vs ``brd-alpha``).  Treating those as different groups would
    silently defeat every uniqueness and overlap rule below, so grouping folds
    case exactly the way the duplicate check does.
    """
    parts: list[str] = []
    for name in fields:
        value = row.get(name)
        parts.append("" if value is None else str(value).strip().casefold())
    return tuple(parts)


# ---------------------------------------------------------------------------
# generic row rules
# ---------------------------------------------------------------------------


def at_least_one_of(*field_names: str, description: str = "") -> RowRule:
    """At least one of ``field_names`` must carry a value.

    Used where a dataset accepts alternative identifiers — e.g. an Rx extract
    keyed either by the supplier's own HCP id or by a previously-crosswalked
    master id.  Requiring both would reject legitimate files; requiring neither
    would let an unjoinable row through to the conformance step, where the
    failure is much harder to explain back to the uploader (plan.md §10.2).
    """
    names = tuple(field_names)
    if len(names) < 2:
        msg = "at_least_one_of needs two or more fields"
        raise ValueError(msg)

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        if any(not _is_blank(row.get(name)) for name in names):
            return _NO_VIOLATIONS
        return (
            RuleViolation(
                code=IssueCode.RULE_AT_LEAST_ONE_REQUIRED,
                field_name=names[0],
                params={"fields": ", ".join(names)},
            ),
        )

    return RowRule(
        name=f"at_least_one_of__{'_'.join(names)}",
        code=IssueCode.RULE_AT_LEAST_ONE_REQUIRED,
        description=description or f"At least one of {', '.join(names)} must be provided.",
        fields=names,
        check=_check,
    )


def dependent_field_required(
    *,
    trigger_field: str,
    required_field: str,
    when: Callable[[Any], bool] | None = None,
    trigger_text: str = "",
    code: IssueCode = IssueCode.RULE_DEPENDENT_FIELD_REQUIRED,
    severity: IssueSeverity | None = None,
    description: str = "",
) -> RowRule:
    """``required_field`` must be present whenever ``trigger_field`` fires.

    ``when`` defaults to "the trigger is boolean-true"; pass a predicate for
    enum triggers.  The predicate is applied to the *coerced* value.  ``code``
    lets a dataset raise a more specific finding than the generic dependency
    code where one exists — a missing compliance justification deserves its own
    error in the catalogue, not a generic "field required" (plan.md §10.2).
    """
    predicate = when if when is not None else (lambda value: _as_bool(value) is True)
    label = trigger_text or f"{trigger_field} is set"

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        trigger = row.get(trigger_field)
        if _is_blank(trigger) or not predicate(trigger):
            return _NO_VIOLATIONS
        if not _is_blank(row.get(required_field)):
            return _NO_VIOLATIONS
        return (
            RuleViolation(
                code=code,
                field_name=required_field,
                severity=severity,
                params={"field": required_field, "condition": label},
            ),
        )

    return RowRule(
        name=f"dependent__{required_field}__on__{trigger_field}",
        code=code,
        description=description or f"{required_field} is required when {label}.",
        fields=(trigger_field, required_field),
        check=_check,
    )


def date_order(
    *,
    earlier_field: str,
    later_field: str,
    allow_equal: bool = True,
    code: IssueCode = IssueCode.RULE_INVALID_EFFECTIVE_RANGE,
    description: str = "",
) -> RowRule:
    """``earlier_field`` must not fall after ``later_field``.

    Applied to campaign windows and invoice/approval pairs.  A reversed window
    is not a cosmetic problem: pre/post attribution windows are cut from these
    dates, so a reversed pair silently empties a cohort (plan.md §10.2 gate
    "Dates and event windows").
    """

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        start = _as_date(row.get(earlier_field))
        end = _as_date(row.get(later_field))
        if start is None or end is None:
            return _NO_VIOLATIONS
        bad = start > end if allow_equal else start >= end
        if not bad:
            return _NO_VIOLATIONS
        return (
            RuleViolation(
                code=code,
                field_name=later_field,
                params={
                    "start_field": earlier_field,
                    "end_field": later_field,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
            ),
        )

    return RowRule(
        name=f"date_order__{earlier_field}__{later_field}",
        code=code,
        description=description
        or (
            f"{earlier_field} must be on or before {later_field}."
            if allow_equal
            else f"{earlier_field} must be strictly before {later_field}."
        ),
        fields=(earlier_field, later_field),
        check=_check,
    )


def effective_range_half_open(
    *,
    from_field: str = "effective_from",
    to_field: str = "effective_to",
) -> RowRule:
    """``[from, to)`` — ``to`` must be strictly after ``from``, or empty.

    The half-open convention is fixed platform-wide (plan.md §9.2): an empty
    ``effective_to`` means "currently in force".  Equal endpoints would describe
    a zero-length window, which no row can ever match — almost always a
    misunderstanding of the closed-interval convention some finance teams use,
    so it is rejected loudly rather than accepted as a no-op row.
    """

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        start = _as_date(row.get(from_field))
        end = _as_date(row.get(to_field))
        if start is None or end is None:
            return _NO_VIOLATIONS
        if end > start:
            return _NO_VIOLATIONS
        return (
            RuleViolation(
                code=IssueCode.RULE_INVALID_EFFECTIVE_RANGE,
                field_name=to_field,
                params={
                    "start_field": from_field,
                    "end_field": to_field,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
            ),
        )

    return RowRule(
        name=f"half_open_range__{from_field}__{to_field}",
        code=IssueCode.RULE_INVALID_EFFECTIVE_RANGE,
        description=(
            f"{to_field} must be strictly after {from_field}; leave it empty for "
            "the currently-in-force row. Ranges are half-open [from, to)."
        ),
        fields=(from_field, to_field),
        check=_check,
    )


def no_future_period(
    field_name: str,
    *,
    severity: IssueSeverity = IssueSeverity.WARNING,
    description: str = "",
) -> RowRule:
    """Flag a period dated beyond today plus the configured grace.

    A month stamped in the future is nearly always a template left over from a
    prior cycle or a two-digit-year misparse.  It is a warning rather than a
    rejection because a legitimately forward-dated planning row exists (see
    ``CANDIDATE_PROGRAMS``), and because rejecting on the clock makes a
    re-upload of the same file behave differently tomorrow.
    """

    def _check(row: RowView, ctx: RuleContext) -> Sequence[RuleViolation]:
        value = _as_date(row.get(field_name))
        if value is None:
            return _NO_VIOLATIONS
        horizon = ctx.today + dt.timedelta(days=ctx.options.future_period_grace_days)
        if value <= horizon:
            return _NO_VIOLATIONS
        return (
            RuleViolation(
                code=IssueCode.RULE_FUTURE_PERIOD,
                field_name=field_name,
                severity=severity,
                params={"field": field_name, "horizon": horizon.isoformat()},
            ),
        )

    return RowRule(
        name=f"no_future_period__{field_name}",
        code=IssueCode.RULE_FUTURE_PERIOD,
        description=description or f"{field_name} should not be dated in the future.",
        fields=(field_name,),
        check=_check,
    )


def approval_requires_approver(
    *,
    status_field: str = "approval_status",
    approver_field: str = "approved_by",
    approved_values: Iterable[str] = ("APPROVED",),
) -> RowRule:
    """An approved cost row must name who approved it.

    Cost approval is an auditable control (plan.md §10.1, "Finance"): an
    ``APPROVED`` row with no approver cannot be defended in a spend review, so
    the platform refuses to record one.
    """
    approved = frozenset(v.strip().upper() for v in approved_values)

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        status = row.get(status_field)
        if _is_blank(status) or str(status).strip().upper() not in approved:
            return _NO_VIOLATIONS
        if not _is_blank(row.get(approver_field)):
            return _NO_VIOLATIONS
        return (
            RuleViolation(
                code=IssueCode.RULE_APPROVAL_WITHOUT_APPROVER,
                field_name=approver_field,
                params={"field": approver_field, "status_field": status_field},
            ),
        )

    return RowRule(
        name="approval_requires_approver",
        code=IssueCode.RULE_APPROVAL_WITHOUT_APPROVER,
        description=f"{approver_field} is required once {status_field} is APPROVED.",
        fields=(status_field, approver_field),
        check=_check,
    )


# ---------------------------------------------------------------------------
# measurement-integrity row rules (plan.md §10.2 "Missing versus zero")
# ---------------------------------------------------------------------------


def distinguish_missing_from_zero(
    *,
    measure_field: str = "nrx",
    observed_field: str = "is_observed",
) -> RowRule:
    """Reject a row that claims a real zero and an unobserved period at once.

    This is the single most consequential rule in the package.  A month with
    ``nrx = 0`` is evidence of *no prescribing*; a month the supplier did not
    cover is evidence of *nothing at all*.  Averaging the two together biases
    every lift estimate downwards, and the bias is invisible in the output —
    the number just looks disappointing.  Plan.md §10.2 therefore makes
    "missing versus zero" its own gate and requires the file to be explicit.

    The shape rejected here is ``nrx = 0`` with ``is_observed = false`` —
    internally contradictory, because a counted zero requires the period to
    have been counted.

    The mirror-image fault (``nrx`` empty on an observed period) belongs to
    :func:`suppression_consistent` and is deliberately *not* duplicated here.
    That rule already knows about ``suppression_flag``, so it can tell a
    declared small-cell suppression from a lost measurement and say so;
    emitting ``RULE_MISSING_VERSUS_ZERO`` for the same row as well would give
    the uploader two error codes and two remediation hints for one fix, and the
    catalogue text for this code ("reports zero ... while marking the period as
    not observed") would not even describe what went wrong.  One cause, one
    message.
    """

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        observed = _as_bool(row.get(observed_field))
        if observed is not False:
            return _NO_VIOLATIONS
        measure = _as_decimal(row.get(measure_field))
        if measure is None or measure != 0:
            return _NO_VIOLATIONS
        return (
            RuleViolation(
                code=IssueCode.RULE_MISSING_VERSUS_ZERO,
                field_name=observed_field,
                params={
                    "field": measure_field,
                    "measure_field": measure_field,
                    "observed_field": observed_field,
                },
            ),
        )

    return RowRule(
        name="distinguish_missing_from_zero",
        code=IssueCode.RULE_MISSING_VERSUS_ZERO,
        description=(
            f"A counted zero and an unobserved period are different facts. Set "
            f"{measure_field}=0 with {observed_field}=true for a real zero, and leave "
            f"{measure_field} empty with {observed_field}=false for a period the supplier "
            "did not cover. The two must never be combined."
        ),
        fields=(measure_field, observed_field),
        check=_check,
    )


def suppression_consistent(
    *,
    flag_field: str = "suppression_flag",
    measure_fields: Sequence[str] = ("nrx", "trx"),
) -> RowRule:
    """A blank measure is only acceptable when the row is flagged suppressed.

    Rx suppliers withhold small-cell counts for privacy.  That is a legitimate
    reason for an empty measure on an observed period, but it has to be
    declared: an undeclared blank is indistinguishable from a broken export,
    and the downstream models treat the two differently (a suppressed cell is
    known-small, a missing cell is unknown).

    The rule is symmetric — a row flagged suppressed that nonetheless carries a
    value is also rejected, because it means the flag is being set
    indiscriminately and can no longer be trusted as an indicator.
    """
    measures = tuple(measure_fields)

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        flag = _as_bool(row.get(flag_field))
        observed = _as_bool(row.get("is_observed"))
        out: list[RuleViolation] = []
        for name in measures:
            value = row.get(name)
            if flag is True and value is not None:
                out.append(
                    RuleViolation(
                        code=IssueCode.RULE_SUPPRESSED_VALUE_PRESENT,
                        field_name=name,
                        params={"field": name, "flag_field": flag_field},
                    )
                )
            elif flag is not True and value is None and observed is True:
                out.append(
                    RuleViolation(
                        code=IssueCode.VALUE_REQUIRED_UNLESS_SUPPRESSED,
                        field_name=name,
                        params={"field": name, "other": flag_field, "flag_field": flag_field},
                    )
                )
        return out

    return RowRule(
        name="suppression_consistent",
        code=IssueCode.VALUE_REQUIRED_UNLESS_SUPPRESSED,
        description=(
            f"Leave {', '.join(measures)} empty only when {flag_field} is true "
            "(supplier small-cell suppression); a suppressed row must not also carry a value."
        ),
        fields=(flag_field, "is_observed", *measures),
        check=_check,
    )


def trx_not_below_nrx(*, nrx_field: str = "nrx", trx_field: str = "trx") -> RowRule:
    """TRx below NRx is a definition mismatch, not a data point.

    Total prescriptions include new ones, so ``trx >= nrx`` holds under every
    standard supplier definition (plan.md §4).  A violation almost always means
    the two columns were mapped the wrong way round or the extract mixes two
    ``supplier_definition_version`` values.  Raised as a warning: the row is
    still loadable and the reviewer, not the parser, should decide which
    interpretation is right.
    """

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        nrx = _as_decimal(row.get(nrx_field))
        trx = _as_decimal(row.get(trx_field))
        if nrx is None or trx is None or trx >= nrx:
            return _NO_VIOLATIONS
        return (
            RuleViolation(
                code=IssueCode.RULE_TRX_LESS_THAN_NRX,
                field_name=trx_field,
                severity=IssueSeverity.WARNING,
                params={"nrx_field": nrx_field, "trx_field": trx_field},
            ),
        )

    return RowRule(
        name="trx_not_below_nrx",
        code=IssueCode.RULE_TRX_LESS_THAN_NRX,
        description=f"{trx_field} should be greater than or equal to {nrx_field}.",
        fields=(nrx_field, trx_field),
        check=_check,
    )


def coverage_factor_sufficient(field_name: str = "coverage_factor") -> RowRule:
    """Warn when a period's panel coverage is too thin to project from.

    ``coverage_factor`` is the share of the market the supplier's panel sees.
    Below the configured threshold the projection multiplier becomes large
    enough that ordinary panel noise dominates the estimate, so the row is
    accepted but marked — plan.md §10.2 "Reconciliation and coverage".
    """

    def _check(row: RowView, ctx: RuleContext) -> Sequence[RuleViolation]:
        value = _as_decimal(row.get(field_name))
        if value is None or value >= ctx.options.coverage_warning_threshold:
            return _NO_VIOLATIONS
        return (
            RuleViolation(
                code=IssueCode.RULE_COVERAGE_BELOW_THRESHOLD,
                field_name=field_name,
                severity=IssueSeverity.WARNING,
                params={
                    "field": field_name,
                    "expected": str(ctx.options.coverage_warning_threshold),
                    "threshold": str(ctx.options.coverage_warning_threshold),
                },
            ),
        )

    return RowRule(
        name="coverage_factor_sufficient",
        code=IssueCode.RULE_COVERAGE_BELOW_THRESHOLD,
        description=f"{field_name} below the review threshold is flagged for review.",
        fields=(field_name,),
        check=_check,
    )


# ---------------------------------------------------------------------------
# attendance rules (plan.md §4: verified attendance is the treatment)
# ---------------------------------------------------------------------------


def verified_requires_strong_source(
    *,
    verified_field: str = "verified_attended",
    source_field: str = "verification_source",
) -> RowRule:
    """``verified_attended = true`` must name how attendance was verified.

    Verified attendance *is* the treatment variable for every causal estimate
    the platform produces (plan.md §4).  A row that asserts attendance with
    ``verification_source = UNVERIFIED`` is an assertion with no evidence
    behind it; admitting it would silently contaminate the treated cohort with
    people who merely registered, which biases lift towards zero and is not
    recoverable downstream.  Hence a hard rejection rather than a warning.
    """

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        verified = _as_bool(row.get(verified_field))
        if verified is not True:
            return _NO_VIOLATIONS
        source = row.get(source_field)
        if (
            _is_blank(source)
            or str(source).strip().upper() == AttendanceVerificationSource.UNVERIFIED.value
        ):
            return (
                RuleViolation(
                    code=IssueCode.RULE_VERIFIED_WITHOUT_SOURCE,
                    field_name=source_field,
                    params={"verified_field": verified_field, "source_field": source_field},
                ),
            )
        return _NO_VIOLATIONS

    return RowRule(
        name="verified_requires_strong_source",
        code=IssueCode.RULE_VERIFIED_WITHOUT_SOURCE,
        description=(
            f"{verified_field}=true requires a {source_field} other than UNVERIFIED. "
            "Verified attendance is the treatment definition and must carry evidence."
        ),
        fields=(verified_field, source_field),
        check=_check,
    )


def attendance_status_consistent(
    *,
    status_field: str = "registration_status",
    verified_field: str = "verified_attended",
) -> RowRule:
    """A cancelled or no-show registration cannot also be a verified attendance.

    Registration status and verified attendance come from different systems
    (the invitation tool and the door), so disagreement is common and
    meaningful.  It is reported as a warning and reconciled by
    :func:`resolve_duplicates` rather than silently resolved here, because the
    door scan is usually right and the registration record usually stale — but
    "usually" is not a basis for discarding evidence without telling anyone.
    """
    # NOT_REGISTERED and WAITLISTED are deliberately absent: a walk-in is a real
    # and common occurrence, and flagging it would train reviewers to ignore the
    # flag. CANCELLED and NO_SHOW are the two that actively contradict evidence
    # of attendance.
    conflicting = frozenset({"CANCELLED", "NO_SHOW"})

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        status = row.get(status_field)
        verified = _as_bool(row.get(verified_field))
        if _is_blank(status) or verified is not True:
            return _NO_VIOLATIONS
        if str(status).strip().upper() not in conflicting:
            return _NO_VIOLATIONS
        return (
            RuleViolation(
                code=IssueCode.RULE_ATTENDANCE_STATUS_CONFLICT,
                field_name=status_field,
                severity=IssueSeverity.WARNING,
                params={"status_field": status_field, "verified_field": verified_field},
            ),
        )

    return RowRule(
        name="attendance_status_consistent",
        code=IssueCode.RULE_ATTENDANCE_STATUS_CONFLICT,
        description=(
            f"{status_field} of CANCELLED or NO_SHOW conflicts with "
            f"{verified_field}=true; the row is kept and flagged for review."
        ),
        fields=(status_field, verified_field),
        check=_check,
    )


# ---------------------------------------------------------------------------
# frame rules
# ---------------------------------------------------------------------------


def no_overlapping_effective_ranges(
    *,
    key_fields: Sequence[str],
    from_field: str = "effective_from",
    to_field: str = "effective_to",
    description: str = "",
) -> FrameRule:
    """No two rows sharing ``key_fields`` may cover the same day.

    Finance assumptions are effective-dated so a contribution-per-NRx can change
    mid-year without rewriting history.  If two rows for the same
    (brand, scenario) overlap, "the assumption in force on date D" stops being a
    function — every ROI figure computed over that window becomes dependent on
    row order, which is not reproducible and not defensible in a finance review
    (plan.md §9.2, §11).

    Ranges are half-open ``[from, to)``, so a row ending 2026-04-01 and one
    starting 2026-04-01 are adjacent, not overlapping.  An empty ``to`` means
    open-ended, and two open-ended rows for the same key always overlap.

    Both offending rows are quarantined rather than rejected: which one is
    wrong is a business question, and dropping the later one by fiat would
    quietly discard the correction the finance team just uploaded.
    """
    keys = tuple(key_fields)

    def _check(rows: Sequence[RowView], _ctx: RuleContext) -> Sequence[FrameViolation]:
        buckets: dict[tuple[str, ...], list[tuple[dt.date, dt.date | None, int]]] = {}
        for row in rows:
            start = _as_date(row.get(from_field))
            if start is None:
                continue  # a malformed date is already reported by the type gate
            end = _as_date(row.get(to_field))
            buckets.setdefault(_group_key(row, keys), []).append((start, end, row.ordinal))

        out: list[FrameViolation] = []
        for key, spans in buckets.items():
            if len(spans) < 2:
                continue
            ordered = sorted(spans, key=lambda item: (item[0], item[2]))
            for index in range(1, len(ordered)):
                prev_start, prev_end, prev_ordinal = ordered[index - 1]
                start, _end, ordinal = ordered[index]
                if prev_end is None or start < prev_end:
                    out.append(
                        FrameViolation(
                            code=IssueCode.RULE_OVERLAPPING_EFFECTIVE_RANGE,
                            ordinals=(prev_ordinal, ordinal),
                            field_name=from_field,
                            params={
                                "key_fields": ", ".join(keys),
                                "key": " | ".join(key),
                                "first": prev_start.isoformat(),
                                "second": start.isoformat(),
                            },
                            drop_ordinals=(prev_ordinal, ordinal),
                        )
                    )
        return tuple(out)

    return FrameRule(
        name="no_overlapping_effective_ranges",
        code=IssueCode.RULE_OVERLAPPING_EFFECTIVE_RANGE,
        description=description
        or (
            f"Rows sharing ({', '.join(keys)}) must have non-overlapping half-open "
            f"[{from_field}, {to_field}) ranges."
        ),
        fields=(*keys, from_field, to_field),
        check=_check,
    )


def single_currency_per_group(
    *,
    group_fields: Sequence[str],
    currency_field: str = "currency",
) -> FrameRule:
    """One currency per grouped total.

    PLAN_REVIEW F-14 forbids implicit currency conversion anywhere in the
    platform.  Two currencies inside the same event's cost lines would make the
    event total a meaningless sum, so the whole group is quarantined for the
    uploader to split or restate.  Nothing here guesses an exchange rate.
    """
    keys = tuple(group_fields)

    def _check(rows: Sequence[RowView], _ctx: RuleContext) -> Sequence[FrameViolation]:
        buckets: dict[tuple[str, ...], dict[str, list[int]]] = {}
        for row in rows:
            code = row.get(currency_field)
            if _is_blank(code):
                continue
            bucket = buckets.setdefault(_group_key(row, keys), {})
            bucket.setdefault(str(code).strip().upper(), []).append(row.ordinal)

        out: list[FrameViolation] = []
        for key, by_currency in buckets.items():
            if len(by_currency) < 2:
                continue
            ordinals = tuple(sorted(o for group in by_currency.values() for o in group))
            out.append(
                FrameViolation(
                    code=IssueCode.RULE_MIXED_CURRENCY_EVENT,
                    ordinals=ordinals,
                    field_name=currency_field,
                    params={
                        "key_fields": ", ".join(keys),
                        "key": " | ".join(key),
                        "currencies": ", ".join(sorted(by_currency)),
                    },
                    drop_ordinals=ordinals,
                )
            )
        return tuple(out)

    return FrameRule(
        name="single_currency_per_group",
        code=IssueCode.RULE_MIXED_CURRENCY_EVENT,
        description=(
            f"All rows sharing ({', '.join(keys)}) must use one {currency_field}; "
            "the platform never converts currencies implicitly."
        ),
        fields=(*keys, currency_field),
        check=_check,
    )


def unambiguous_crosswalk(
    *,
    source_fields: Sequence[str] = ("source_system", "source_hcp_id"),
    master_field: str = "master_hcp_id",
    from_field: str = "effective_from",
    to_field: str = "effective_to",
    status_field: str = "status",
) -> FrameRule:
    """One source identifier may not map to two masters in the same window.

    Identity resolution is the join that makes everything else possible: an Rx
    row, an attendance row and a marketing-touch row are the *same* prescriber
    only because the crosswalk says so.  A source id pointing at two master ids
    over overlapping effective windows makes that join non-deterministic — the
    same HCP would land in both the treated and control arm depending on join
    order.

    Plan.md §9.4 is explicit that ambiguous matches go to a review queue and are
    never auto-picked, so every row in the ambiguous set is quarantined with
    :data:`IssueCode.IDENTITY_AMBIGUOUS_CROSSWALK`.  Rows already marked
    ``AMBIGUOUS``/``REJECTED`` by the supplier are excluded from the check: they
    are declared-unresolved by construction and are meant to reach the queue.
    """
    keys = tuple(source_fields)
    ignored_statuses = frozenset({"AMBIGUOUS", "REJECTED"})

    def _check(rows: Sequence[RowView], _ctx: RuleContext) -> Sequence[FrameViolation]:
        buckets: dict[tuple[str, ...], list[RowView]] = {}
        for row in rows:
            status = row.get(status_field)
            if not _is_blank(status) and str(status).strip().upper() in ignored_statuses:
                continue
            if _is_blank(row.get(master_field)):
                continue
            buckets.setdefault(_group_key(row, keys), []).append(row)

        out: list[FrameViolation] = []
        for key, members in buckets.items():
            if len(members) < 2:
                continue
            conflicting: set[int] = set()
            masters: set[str] = set()
            for index, left in enumerate(members):
                for right in members[index + 1 :]:
                    left_master = str(left.get(master_field)).strip().casefold()
                    right_master = str(right.get(master_field)).strip().casefold()
                    if left_master == right_master:
                        continue
                    if not _windows_overlap(left, right, from_field, to_field):
                        continue
                    conflicting.update({left.ordinal, right.ordinal})
                    masters.update({left_master, right_master})
            if conflicting:
                ordinals = tuple(sorted(conflicting))
                out.append(
                    FrameViolation(
                        code=IssueCode.IDENTITY_AMBIGUOUS_CROSSWALK,
                        ordinals=ordinals,
                        field_name=master_field,
                        params={
                            "source": " | ".join(key),
                            "master_count": str(len(masters)),
                        },
                        drop_ordinals=ordinals,
                    )
                )
        return tuple(out)

    return FrameRule(
        name="unambiguous_crosswalk",
        code=IssueCode.IDENTITY_AMBIGUOUS_CROSSWALK,
        description=(
            f"A ({', '.join(keys)}) pair must resolve to one {master_field} within any "
            "effective window; ambiguous mappings are quarantined for review, never auto-picked."
        ),
        fields=(*keys, master_field, from_field, to_field, status_field),
        check=_check,
    )


def _windows_overlap(
    left: RowView,
    right: RowView,
    from_field: str,
    to_field: str,
) -> bool:
    """Half-open ``[from, to)`` overlap test tolerant of absent dates.

    An undated crosswalk row is treated as always-in-force.  That is the
    conservative reading: it makes conflicts *more* likely to be caught, and a
    false quarantine costs a review click while a false accept corrupts a cohort.
    """
    left_start = _as_date(left.get(from_field)) or dt.date.min
    right_start = _as_date(right.get(from_field)) or dt.date.min
    left_end = _as_date(left.get(to_field)) or dt.date.max
    right_end = _as_date(right.get(to_field)) or dt.date.max
    return left_start < right_end and right_start < left_end


# ---------------------------------------------------------------------------
# duplicate handling
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DuplicateOutcome:
    """What happened to one row under the contract's duplicate policy."""

    ordinal: int
    code: IssueCode
    severity: IssueSeverity | None = None
    params: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.params is None:
            object.__setattr__(self, "params", {})


@dataclass(frozen=True, slots=True)
class DuplicateResolution:
    """Result of applying a contract's duplicate policy to a whole frame."""

    #: Ordinals that survive and should reach the accepted frame.
    kept: frozenset[int]
    #: Ordinals dropped as superseded, rejected or quarantined.
    dropped: frozenset[int]
    #: Ordinals that must be quarantined rather than plainly rejected.
    quarantined: frozenset[int]
    #: One entry per row that the policy acted on, for the error report.
    outcomes: tuple[DuplicateOutcome, ...]


def _verification_rank(row: RowView, source_field: str) -> int:
    """Evidence strength: 2 = strong, 1 = weak-but-named, 0 = unverified/absent."""
    raw = row.get(source_field)
    if _is_blank(raw):
        return 0
    token = str(raw).strip().upper()
    try:
        source = AttendanceVerificationSource(token)
    except ValueError:
        return 0
    if source is AttendanceVerificationSource.UNVERIFIED:
        return 0
    return 2 if source.is_strong else 1


def resolve_duplicates(
    rows: Sequence[RowView],
    contract: DatasetContract,
    _ctx: RuleContext,
) -> DuplicateResolution:
    """Apply ``contract.duplicate_policy`` to rows sharing a natural key.

    The four policies exist because "duplicate" means four different things
    across the twelve datasets (plan.md §10.2 gate "Unique keys"):

    ``REJECT``
        Reference and master data.  Two rows claiming to define the same brand
        are a broken export; neither can be trusted, so both are rejected.

    ``LAST_WINS`` / ``FIRST_WINS``
        Transactional restatements.  Rx and cost extracts are commonly
        re-issued with corrections appended; the loser is dropped with
        :data:`IssueCode.DUPLICATE_SUPERSEDED` so the reviewer can see the
        restatement happened rather than wondering where a row went.

    ``RECONCILE``
        Attendance only.  The same person can legitimately appear twice — once
        from the registration export, once from the badge scanner — and those
        rows carry *different evidence*, not redundant copies.  Merging them by
        arrival order would let a stale registration override a door scan.  So:

        1. The strongest ``verification_source`` wins (badge scan and webinar
           platform log outrank a signed sheet or a self-report).
        2. If two rows of *equal, strong* provenance disagree about whether the
           person attended, no rule can arbitrate — one of the two systems is
           wrong and only a human knows which.  Every row in that group is
           **quarantined** with
           :data:`IssueCode.RULE_ATTENDANCE_CONFLICTING_STRONG_SOURCE`.  Picking
           one silently would put a possibly-absent HCP into the treated cohort,
           which is exactly the failure mode plan.md §4 warns about.
        3. Equal-strength rows that *agree* are collapsed to the first, reported
           as :data:`IssueCode.DUPLICATE_RECONCILED`.
    """
    if not contract.natural_key:
        return DuplicateResolution(
            kept=frozenset(row.ordinal for row in rows),
            dropped=frozenset(),
            quarantined=frozenset(),
            outcomes=(),
        )

    buckets: dict[tuple[str, ...], list[RowView]] = {}
    for row in rows:
        buckets.setdefault(_group_key(row, contract.natural_key), []).append(row)

    kept: set[int] = set()
    dropped: set[int] = set()
    quarantined: set[int] = set()
    outcomes: list[DuplicateOutcome] = []
    key_label = ", ".join(contract.natural_key)

    for members in buckets.values():
        if len(members) == 1:
            kept.add(members[0].ordinal)
            continue

        policy = contract.duplicate_policy
        if policy == "REJECT":
            for row in members:
                dropped.add(row.ordinal)
                outcomes.append(
                    DuplicateOutcome(
                        ordinal=row.ordinal,
                        code=IssueCode.DUPLICATE_NATURAL_KEY,
                        params={"key_fields": key_label, "count": str(len(members))},
                    )
                )
            continue

        if policy in {"LAST_WINS", "FIRST_WINS"}:
            winner = members[-1] if policy == "LAST_WINS" else members[0]
            kept.add(winner.ordinal)
            for row in members:
                if row.ordinal == winner.ordinal:
                    continue
                dropped.add(row.ordinal)
                outcomes.append(
                    DuplicateOutcome(
                        ordinal=row.ordinal,
                        code=IssueCode.DUPLICATE_SUPERSEDED,
                        severity=IssueSeverity.WARNING,
                        params={
                            "key_fields": key_label,
                            "policy": policy,
                            "winning_row": str(winner.row_number),
                        },
                    )
                )
            continue

        _reconcile_group(
            members,
            key_label=key_label,
            kept=kept,
            dropped=dropped,
            quarantined=quarantined,
            outcomes=outcomes,
        )

    return DuplicateResolution(
        kept=frozenset(kept),
        dropped=frozenset(dropped),
        quarantined=frozenset(quarantined),
        outcomes=tuple(sorted(outcomes, key=lambda o: o.ordinal)),
    )


def _reconcile_group(
    members: Sequence[RowView],
    *,
    key_label: str,
    kept: set[int],
    dropped: set[int],
    quarantined: set[int],
    outcomes: list[DuplicateOutcome],
    verified_field: str = "verified_attended",
    source_field: str = "verification_source",
) -> None:
    """RECONCILE policy for one natural-key group. See :func:`resolve_duplicates`."""
    ranked = [(_verification_rank(row, source_field), row) for row in members]
    best_rank = max(rank for rank, _ in ranked)
    finalists = [row for rank, row in ranked if rank == best_rank]

    if len(finalists) > 1:
        verdicts = {_as_bool(row.get(verified_field)) for row in finalists}
        if len(verdicts) > 1:
            code = (
                IssueCode.RULE_ATTENDANCE_CONFLICTING_STRONG_SOURCE
                if best_rank == 2
                else IssueCode.RULE_ATTENDANCE_CONFLICTING_EVIDENCE
            )
            for row in members:
                quarantined.add(row.ordinal)
                dropped.add(row.ordinal)
                outcomes.append(
                    DuplicateOutcome(
                        ordinal=row.ordinal,
                        code=code,
                        severity=IssueSeverity.QUARANTINE,
                        params={
                            "key_fields": key_label,
                            "count": str(len(finalists)),
                            "source_field": source_field,
                        },
                    )
                )
            return

    winner = finalists[0]
    kept.add(winner.ordinal)
    for row in members:
        if row.ordinal == winner.ordinal:
            continue
        dropped.add(row.ordinal)
        outcomes.append(
            DuplicateOutcome(
                ordinal=row.ordinal,
                code=IssueCode.DUPLICATE_RECONCILED,
                severity=IssueSeverity.WARNING,
                params={
                    "key_fields": key_label,
                    "winning_row": str(winner.row_number),
                    "winning_source": str(winner.get(source_field) or "(unspecified)"),
                },
            )
        )
