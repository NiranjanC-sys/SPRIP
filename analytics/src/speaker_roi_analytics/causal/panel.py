"""Cohort construction: from invitation lists to an analysable panel.

This module answers one question - *which (event, prescriber) pairs can we
legitimately compare, and why was everyone else dropped?* - and it answers the
second half as carefully as the first.

The exclusion ledger is the point
---------------------------------
Every unit that leaves the funnel leaves with an
:class:`~speaker_roi_core.enums.ExclusionReason` attached. This is not
bookkeeping for its own sake. A cohort of 40 attendees out of 900 invitees is
either a clean, well-identified comparison or a bug, and the only thing that
distinguishes those two cases is being able to say where the other 860 went. So
the funnel is materialised (:attr:`Cohort.exclusions`) rather than expressed as a
chain of boolean filters, and the UI shows it (plan.md §12.1). "Why is this event
not estimable?" must always have an answer that names a rule.

Two subtleties worth stating plainly, because both are easy to get wrong in a way
that produces a *better-looking* number:

**Unverified attendees are excluded from both arms, not folded into control.**
Somebody recorded as having attended, whose attendance was never verified, is not
a known non-attendee - they are unknown. Treating them as controls contaminates
the comparison group with treated units, which biases the estimate toward zero;
treating them as treated inflates the denominator with people who may never have
come. They are dropped, and counted.

The distinction is narrow and worth being exact about: a NO_SHOW or CANCELLED
registration is *also* unverified, but it is not ambiguous at all - it is a
positive record that the prescriber did not attend, which makes them one of the
better controls available, being someone who was invited and interested enough to
register. Only ``ATTENDED`` without verification is genuinely unknown.

**The event month belongs to neither window.** Attendance happens partway through
it, so part of that month is pre-exposure and part is post. Assigning it to either
window moves the estimate for a calendar reason. It is dropped from both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
import structlog

from speaker_roi_core.enums import (
    AttendanceStatus,
    CohortArm,
    EventStatus,
    ExclusionReason,
    OutcomeMetric,
)

from .spec import EstimatorSpec

__all__ = [
    "Cohort",
    "PanelFrames",
    "build_cohort",
    "month_index",
]

_LOG = structlog.get_logger(__name__)

#: Columns the cohort carries out to the propensity, matching and estimation
#: stages. Fixed here so a downstream stage cannot quietly depend on a column
#: that only exists for some inputs.
COHORT_COLUMNS: Final[tuple[str, ...]] = (
    "tenant_id",
    "event_id",
    "hcp_id",
    "brand_id",
    "event_month_index",
    "arm",
    "is_treated",
)


def month_index(months: pd.Series, anchor: pd.Timestamp) -> pd.Series:
    """Whole months from ``anchor``, as an integer.

    Month arithmetic on dates is a recurring source of off-by-one errors once
    time zones and month lengths get involved, so every date in this package is
    reduced to an integer offset from one anchor exactly once, here.
    """
    stamps = pd.to_datetime(months)
    return (stamps.dt.year - anchor.year) * 12 + (stamps.dt.month - anchor.month)


@dataclass(frozen=True, slots=True)
class PanelFrames:
    """The platform tables the cohort builder reads.

    Passed as a bundle rather than as eight arguments so that the same call works
    against synthetic frames, a database query result, or a fixture, and so that
    adding an input is a visible change to one type.
    """

    events: pd.DataFrame
    invitations: pd.DataFrame
    attendance: pd.DataFrame
    rx_monthly: pd.DataFrame
    hcps: pd.DataFrame
    marketing_activity: pd.DataFrame
    #: Anchor month for :func:`month_index`. Must be the same anchor the events'
    #: ``event_month_index`` was computed against.
    anchor: pd.Timestamp

    def brand_outcome(self, metric: OutcomeMetric) -> pd.DataFrame:
        """Observed outcome summed to (hcp, brand, month).

        The estimand is defined on the *brand* the program promoted, not on a
        single SKU: a speaker program for a brand moves prescribing across that
        brand's products, and picking one product would measure a share shift
        inside the brand rather than the program's effect.

        Suppressed and unobserved rows are dropped rather than zero-filled. A
        month absent from a claims panel means "not reported", and reading it as
        "no prescriptions" would turn missing data into a measured decline -
        exactly the direction that makes a program look effective when the panel
        coverage simply improved.
        """
        column = metric.value.lower()
        rx = self.rx_monthly
        observed = rx[rx["is_observed"] & ~rx["suppression_flag"].astype(bool)]
        out = observed.groupby(["hcp_id", "brand_id", "month"], as_index=False)[column].sum()
        out = out.rename(columns={column: "outcome"})
        out["mi"] = month_index(out["month"], self.anchor)
        return out[["hcp_id", "brand_id", "mi", "outcome"]]


@dataclass(frozen=True, slots=True)
class Cohort:
    """An analysable cohort plus the full record of what was excluded.

    ``units`` is one row per surviving (event, prescriber) pair with its arm and
    its window aggregates. ``exclusions`` is one row per *dropped* pair with the
    reason. The two are disjoint and together account for every invitation
    considered, which :meth:`reconciles` checks.
    """

    units: pd.DataFrame
    exclusions: pd.DataFrame
    monthly: pd.DataFrame
    #: Monthly outcomes over :attr:`~.spec.EstimatorSpec.anchor_offsets`, strictly
    #: earlier than :attr:`monthly` and disjoint from it. Deliberately a separate
    #: frame rather than extra rows in ``monthly``: every existing consumer of
    #: ``monthly`` filters on ``offset < 0`` to mean "the baseline window", and
    #: widening that frame would silently redefine the baseline, the pre-trend test
    #: and the feature windows all at once. Matching reads this; nothing else does.
    anchor: pd.DataFrame
    spec: EstimatorSpec
    n_invitations_considered: int

    @property
    def treated(self) -> pd.DataFrame:
        return self.units[self.units["is_treated"]]

    @property
    def controls(self) -> pd.DataFrame:
        return self.units[~self.units["is_treated"]]

    def funnel(self) -> pd.DataFrame:
        """Counts by exclusion reason, for the Data Health and Method panels."""
        if self.exclusions.empty:
            counts = pd.DataFrame({"reason": [], "units": []})
        else:
            counts = (
                self.exclusions.groupby("reason", as_index=False)
                .size()
                .rename(columns={"size": "units"})
                .sort_values("units", ascending=False)
            )
        return counts.reset_index(drop=True)

    def reconciles(self) -> bool:
        """Every invitation considered is either analysable or excluded, exactly once.

        Cheap, and it catches the whole class of bug where a filter is applied
        twice or a merge fans out - which shows up as a plausible-looking cohort
        rather than as an error.
        """
        return len(self.units) + len(self.exclusions) == self.n_invitations_considered


def _drop(frame: pd.DataFrame, mask: np.ndarray, reason: ExclusionReason) -> pd.DataFrame:
    """Rows of ``frame`` selected by ``mask``, tagged with why they left."""
    out = frame.loc[mask, ["tenant_id", "event_id", "hcp_id"]].copy()
    out["reason"] = reason.value
    return out


def build_cohort(frames: PanelFrames, spec: EstimatorSpec) -> Cohort:
    """Assemble the treated and control arms for every completed event.

    The order of the exclusions is deliberate: structural reasons first (the event
    did not happen, the attendance record is ambiguous), then data-availability
    reasons (no usable pre or post window), then identification reasons
    (contamination). Ordering matters only for attribution - a unit dropped for two
    reasons is reported under the first - and reporting "event cancelled" is more
    useful than reporting "insufficient post coverage" for the same unit.
    """
    events = frames.events
    completed = events[events["status"] == EventStatus.COMPLETED.value]

    keys = ["tenant_id", "event_id", "hcp_id"]
    event_cols = ["event_id", "brand_id", "event_month_index"]
    pairs = frames.invitations[keys].merge(completed[event_cols], on="event_id", how="inner")
    considered = len(pairs)

    # Invitations to events that never happened. They are counted rather than
    # filtered silently, because "we invited 900 people to events that were
    # cancelled" is a planning finding in its own right.
    cancelled_pairs = frames.invitations[keys].merge(
        events.loc[events["status"] != EventStatus.COMPLETED.value, ["event_id"]],
        on="event_id",
        how="inner",
    )
    ledger = [
        _drop(
            cancelled_pairs,
            np.ones(len(cancelled_pairs), dtype=bool),
            ExclusionReason.EVENT_CANCELLED,
        )
    ]

    # --- arm assignment ---------------------------------------------------
    att = frames.attendance
    is_verified = att["is_verified"].astype(bool)
    # See the module docstring on why this is ``ATTENDED and not verified`` rather
    # than simply ``not verified``: a NO_SHOW is unverified and perfectly
    # informative.
    claimed_attended = (att["attendance_status"] == AttendanceStatus.ATTENDED.value) & ~is_verified
    verified = att.loc[is_verified, ["event_id", "hcp_id"]].drop_duplicates()
    claimed = att.loc[claimed_attended, ["event_id", "hcp_id"]].drop_duplicates()

    pairs = pairs.merge(verified.assign(_treated=True), on=["event_id", "hcp_id"], how="left")
    pairs = pairs.merge(claimed.assign(_claimed=True), on=["event_id", "hcp_id"], how="left")
    # ``notna`` rather than ``fillna(False)``: the merge flag is True-or-missing,
    # and filling an object column provokes a pandas downcast warning for no gain.
    pairs["is_treated"] = pairs["_treated"].notna()
    unverified = pairs["_claimed"].notna() & ~pairs["is_treated"]
    pairs = pairs.drop(columns=["_treated", "_claimed"])

    ledger.append(_drop(pairs, unverified.to_numpy(), ExclusionReason.UNVERIFIED_ATTENDANCE))
    pairs = pairs[~unverified.to_numpy()].reset_index(drop=True)

    # --- window aggregates ------------------------------------------------
    outcome = frames.brand_outcome(spec.outcome)
    monthly = pairs[["tenant_id", "event_id", "hcp_id", "brand_id", "event_month_index"]].merge(
        outcome, on=["hcp_id", "brand_id"], how="inner"
    )
    monthly["offset"] = monthly["mi"] - monthly["event_month_index"]
    lo, hi = -spec.pre_window_months, spec.post_window_months
    # Sliced off before ``monthly`` is narrowed, so the anchor window costs one
    # filter rather than a second pass over the outcome panel.
    anchor_lo = -(spec.pre_window_months + spec.anchor_window_months)
    anchor = monthly[(monthly["offset"] >= anchor_lo) & (monthly["offset"] < lo)].reset_index(
        drop=True
    )
    monthly = monthly[(monthly["offset"] >= lo) & (monthly["offset"] <= hi)]
    # The event month is in neither window, so it is removed here rather than
    # being carried around and remembered about at every use site.
    monthly = monthly[monthly["offset"] != 0].reset_index(drop=True)

    is_pre = monthly["offset"] < 0
    agg = (
        monthly.assign(
            pre_value=np.where(is_pre, monthly["outcome"], np.nan),
            post_value=np.where(~is_pre, monthly["outcome"], np.nan),
        )
        .groupby(["event_id", "hcp_id"], as_index=False)
        .agg(
            pre_mean=("pre_value", "mean"),
            pre_months=("pre_value", "count"),
            post_mean=("post_value", "mean"),
            post_months=("post_value", "count"),
        )
    )
    pairs = pairs.merge(agg, on=["event_id", "hcp_id"], how="left")
    pairs[["pre_months", "post_months"]] = (
        pairs[["pre_months", "post_months"]].fillna(0).astype(int)
    )

    # No outcome series at all is a different finding from a short one, and
    # conflating them makes ordinary panel coverage look like a data-quality
    # incident. Roughly a fifth of invitees are simply not in the promoted brand's
    # Rx panel; that is what claims coverage looks like, not a defect.
    no_series = ((pairs["pre_months"] == 0) & (pairs["post_months"] == 0)).to_numpy()
    ledger.append(_drop(pairs, no_series, ExclusionReason.OUTCOME_SUPPRESSED))
    pairs = pairs[~no_series].reset_index(drop=True)

    thin_pre = (pairs["pre_months"] < spec.min_pre_months).to_numpy()
    ledger.append(_drop(pairs, thin_pre, ExclusionReason.INSUFFICIENT_PRE_HISTORY))
    pairs = pairs[~thin_pre].reset_index(drop=True)

    # The anchor window is a requirement of the design, not a nicety, so a unit
    # without one is excluded here rather than left to fail silently at the caliper.
    # The distinction matters for how the funnel reads: "this prescriber had no
    # comparable counterpart" and "this prescriber had no history to compare on" are
    # different findings, and only the first is a matching problem. Folding the
    # second into ``NO_MATCH_WITHIN_CALIPER`` also corrupts matched retention, which
    # is gated - a tenant onboarding with two years of claims would look like a
    # matching failure rather than a coverage one.
    anchor_months = (
        anchor.groupby(["event_id", "hcp_id"]).size().rename("anchor_months")
        if not anchor.empty
        else pd.Series(dtype=int, name="anchor_months")
    )
    observed = (
        pairs.set_index(["event_id", "hcp_id"]).index.map(anchor_months).to_numpy(dtype=float)
    )
    thin_anchor = ~(observed >= spec.min_anchor_months)
    ledger.append(_drop(pairs, thin_anchor, ExclusionReason.INSUFFICIENT_PRE_HISTORY))
    pairs = pairs[~thin_anchor].reset_index(drop=True)

    thin_post = (pairs["post_months"] < spec.min_post_months).to_numpy()
    ledger.append(_drop(pairs, thin_post, ExclusionReason.INSUFFICIENT_POST_COVERAGE))
    pairs = pairs[~thin_post].reset_index(drop=True)

    # --- contamination ----------------------------------------------------
    # A treated unit with a second verified same-brand attendance inside its post
    # window has two overlapping exposures whose effects cannot be separated. This
    # is computed over *verified* attendances only: an invitation the prescriber
    # ignored exposes them to nothing.
    contaminated = _overlapping(pairs, frames, spec)
    ledger.append(_drop(pairs, contaminated, ExclusionReason.OVERLAPPING_EXPOSURE))
    pairs = pairs[~contaminated].reset_index(drop=True)

    # ...and the same rule pointed backwards. See ``exclude_prior_exposure`` on the
    # spec for why this applies to controls as well as attendees.
    if spec.exclude_prior_exposure:
        prior = _prior_exposure(pairs, frames, spec)
        ledger.append(_drop(pairs, prior, ExclusionReason.NOT_FIRST_ELIGIBLE_EVENT))
        pairs = pairs[~prior].reset_index(drop=True)

    pairs["arm"] = np.where(pairs["is_treated"], CohortArm.TREATMENT.value, CohortArm.CONTROL.value)
    exclusions = pd.concat(ledger, ignore_index=True) if ledger else pd.DataFrame()
    monthly = monthly.merge(
        pairs[["event_id", "hcp_id", "is_treated"]], on=["event_id", "hcp_id"], how="inner"
    )
    anchor = anchor.merge(
        pairs[["event_id", "hcp_id", "is_treated"]], on=["event_id", "hcp_id"], how="inner"
    )

    cohort = Cohort(
        units=pairs.reset_index(drop=True),
        exclusions=exclusions,
        monthly=monthly,
        anchor=anchor,
        spec=spec,
        n_invitations_considered=considered + len(cancelled_pairs),
    )
    _LOG.info(
        "causal.cohort.built",
        spec=spec.fingerprint,
        considered=cohort.n_invitations_considered,
        treated=int(pairs["is_treated"].sum()),
        controls=int((~pairs["is_treated"]).sum()),
        excluded=len(exclusions),
        reconciles=cohort.reconciles(),
    )
    return cohort


def _other_attendances(frames: PanelFrames) -> pd.DataFrame:
    """Verified attendances with their brand and month, for the exposure windows.

    Deduplicated: the source data legitimately contains repeated attendance rows
    for the same person and event, and a merge against them would fan out.
    """
    att = frames.attendance
    verified = att.loc[att["is_verified"].astype(bool), ["event_id", "hcp_id"]].drop_duplicates()
    return verified.merge(
        frames.events[["event_id", "brand_id", "event_month_index"]], on="event_id", how="inner"
    ).rename(columns={"event_id": "other_event_id", "event_month_index": "other_month"})


def _exposure_window_hits(pairs: pd.DataFrame, frames: PanelFrames, lo: int, hi: int) -> pd.Series:
    """Units with another verified same-brand attendance in month offsets [lo, hi].

    Both contamination rules are this same question asked over a different range,
    so they share the implementation rather than each rolling their own join.
    """
    subject = pairs[["event_id", "hcp_id", "brand_id", "event_month_index"]]
    joined = subject.merge(_other_attendances(frames), on=["hcp_id", "brand_id"], how="left")
    gap = joined["other_month"] - joined["event_month_index"]
    inside = ((joined["other_event_id"] != joined["event_id"]) & (gap >= lo) & (gap <= hi)).fillna(
        False
    )
    hit = joined.loc[inside, ["event_id", "hcp_id"]].drop_duplicates()
    flagged = pairs.merge(hit.assign(_hit=True), on=["event_id", "hcp_id"], how="left")
    return flagged["_hit"].notna()


def _prior_exposure(pairs: pd.DataFrame, frames: PanelFrames, spec: EstimatorSpec) -> np.ndarray:
    """Units carrying a decaying effect tail from an earlier same-brand program.

    The window is the baseline window itself: an exposure older than that has
    decayed to nothing by the time the pre period starts, and excluding on it would
    throw away most repeat-invitee history for no identification gain.
    """
    return _exposure_window_hits(pairs, frames, -spec.pre_window_months, -1).to_numpy()


def _overlapping(pairs: pd.DataFrame, frames: PanelFrames, spec: EstimatorSpec) -> np.ndarray:
    """Treated units with another verified same-brand attendance in the post window.

    Controls are never flagged: they were not exposed by this event, so a second
    program does not confound *this* comparison. It does make them a worse control
    (they are exposed to something), which is why the same prescriber's other
    attendance shows up as a treated unit for that other event and is handled
    there.
    """
    hits = _exposure_window_hits(pairs, frames, 1, spec.post_window_months)
    return (hits & pairs["is_treated"]).to_numpy()
