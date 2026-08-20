"""Deliberate data defects (plan.md §11, §10.2, §12.3).

A synthetic dataset that is clean proves nothing. Every rate in this module
exists so that exactly one gate in the platform fires on real data rather than
on a hand-written unit fixture:

===========================  ==================================================
Defect                       What it must force
===========================  ==================================================
Unmatched source IDs         ``IdentityMatchStatus.UNMATCHED`` quarantine
Ambiguous source IDs         steward decision, never an automatic guess
Duplicate attendance         deterministic, auditable reconciliation
Rx gaps                      "missing month" != "zero month"
Small-cell suppression       null outcome with a reason, not a zero
Cost outliers                finance outlier review
Cancelled events             falsification: invitations exist, effect is zero
Sabotaged events             ``EvidenceStatus.NOT_RELIABLY_ESTIMABLE``
===========================  ==================================================

The distinction that costs teams the most money is the third one. A missing
month is an **absent row**. A genuine zero is a **present row with nrx = 0 and
is_observed = true**. A suppressed cell is a **present row with a null nrx and
suppression_flag = true**. Any pipeline that forward-fills, zero-fills or
dropna()s across those three cases produces a different ATT, so all three are
present here and the gold frames carry the flags that tell them apart.

Imperfections are applied **last**, to already-final frames, and never to the
ground truth. The truth frame keeps saying what actually happened; the observed
data is what the platform is allowed to see. That gap is the entire point.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from speaker_roi_core.enums import (
    AttendanceStatus,
    AttendanceVerificationSource,
    IdentityMatchStatus,
    MatchMethod,
)

from .config import SyntheticProfile
from .events import EventPlan

__all__ = ["ImperfectionReport", "apply_imperfections"]


@dataclass(slots=True)
class ImperfectionReport:
    """What was actually done, for the manifest and the validation suite."""

    counts: dict[str, int] = field(default_factory=dict)

    def record(self, name: str, value: int) -> None:
        self.counts[name] = int(value)


def apply_imperfections(
    profile: SyntheticProfile,
    plan: EventPlan,
    frames: dict[str, pd.DataFrame],
    generator: np.random.Generator,
) -> ImperfectionReport:
    """Apply every defect in place on ``frames``; return what was done.

    ``frames`` is keyed by gold table name. The function mutates the dict
    (replacing frames it has to rebuild) rather than returning a new one, so the
    generator's stage list stays flat and the peak memory does not double.
    """
    report = ImperfectionReport()
    _degrade_crosswalk(profile, frames, generator, report)
    _duplicate_attendance(profile, frames, generator, report)
    _shred_rx(profile, plan, frames, generator, report)
    _cost_outliers(profile, frames, generator, report)
    return report


def _degrade_crosswalk(
    profile: SyntheticProfile,
    frames: dict[str, pd.DataFrame],
    generator: np.random.Generator,
    report: ImperfectionReport,
) -> None:
    """Break a share of the identity crosswalk (plan.md §10.2 step 8).

    An UNMATCHED row keeps its source identifier and loses its ``hcp_id`` - that
    is the whole content of "we received data for a prescriber we cannot
    resolve". Rows that still carry an ``hcp_id`` while claiming to be unmatched
    would let a lazy pipeline join through them anyway, which is exactly the bug
    this defect is meant to expose.
    """
    rates = profile.imperfections
    crosswalk = frames["hcp_crosswalk"]
    n = crosswalk.shape[0]
    draw = generator.random(n)
    unmatched = draw < rates.unmatched_source_id_rate
    ambiguous = (draw >= rates.unmatched_source_id_rate) & (
        draw < rates.unmatched_source_id_rate + rates.ambiguous_source_id_rate
    )

    status = crosswalk["match_status"].to_numpy(dtype=object).copy()
    method = crosswalk["match_method"].to_numpy(dtype=object).copy()
    confidence = crosswalk["match_confidence"].to_numpy(dtype=np.float64).copy()
    hcp_id = crosswalk["hcp_id"].to_numpy(dtype=object).copy()

    status[unmatched] = IdentityMatchStatus.UNMATCHED.value
    method[unmatched] = None
    confidence[unmatched] = np.nan
    hcp_id[unmatched] = None

    status[ambiguous] = IdentityMatchStatus.AMBIGUOUS.value
    method[ambiguous] = MatchMethod.PROBABILISTIC.value
    # Two plausible masters: confidence is high enough to tempt an automatic
    # match and low enough that doing so would be wrong.
    confidence[ambiguous] = np.round(generator.uniform(0.55, 0.78, int(ambiguous.sum())), 4)
    hcp_id[ambiguous] = None

    crosswalk["match_status"] = status
    crosswalk["match_method"] = method
    crosswalk["match_confidence"] = confidence
    crosswalk["hcp_id"] = hcp_id
    report.record("crosswalk_unmatched", int(unmatched.sum()))
    report.record("crosswalk_ambiguous", int(ambiguous.sum()))


def _duplicate_attendance(
    profile: SyntheticProfile,
    frames: dict[str, pd.DataFrame],
    generator: np.random.Generator,
    report: ImperfectionReport,
) -> None:
    """Resubmit a share of attendance rows with a conflicting source.

    The duplicate disagrees on ``verification_source`` and on
    ``is_verified``, which is what makes reconciliation a *decision* rather
    than a ``drop_duplicates()``. plan.md §10.2 requires the rule to be
    deterministic and auditable: the platform has to choose (and record why) -
    a badge scan beats a self-attestation - not silently keep the first row.
    """
    rates = profile.imperfections
    attendance = frames["attendance"]
    n = attendance.shape[0]
    picked = np.flatnonzero(generator.random(n) < rates.duplicate_attendance_rate)
    if picked.size == 0:  # pragma: no cover - rate is never zero in shipped profiles
        report.record("duplicate_attendance", 0)
        return
    duplicate = attendance.iloc[picked].copy()
    duplicate["verification_source"] = AttendanceVerificationSource.UNVERIFIED.value
    # The conflicting submission claims registration without verified presence.
    duplicate["is_verified"] = False
    duplicate["attendance_status"] = AttendanceStatus.REGISTERED.value
    # Filed a few days later by a different system, so ordering alone cannot
    # resolve it and a real precedence rule is required.
    duplicate["attended_on"] = duplicate["attended_on"].to_numpy() + generator.integers(
        1, 6, picked.size
    ).astype("timedelta64[D]")
    frames["attendance"] = pd.concat([attendance, duplicate], ignore_index=True)
    report.record("duplicate_attendance", int(picked.size))


def _shred_rx(
    profile: SyntheticProfile,
    plan: EventPlan,
    frames: dict[str, pd.DataFrame],
    generator: np.random.Generator,
    report: ImperfectionReport,
) -> None:
    """Gaps, small-cell suppression, and the low-coverage sabotage.

    Three distinct states, and the difference between them is load-bearing:

    * **gap** - the row is removed entirely. The vendor never delivered it.
    * **suppression** - the row stays, ``nrx``/``trx`` are null and
      ``suppression_flag`` is true. The vendor delivered "too few scripts to
      report", which is *not* zero.
    * **genuine zero** - the row stays with ``nrx = 0`` and ``is_observed``
      true. Already produced by the DGP wherever the Poisson draw was zero;
      nothing to do here, and nothing may overwrite it.
    """
    rates = profile.imperfections
    rx = frames["rx_monthly"]
    hcp = rx["hcp_id"].to_numpy()
    brand = rx["brand_id"].to_numpy()
    month = rx["month"].to_numpy()

    # --- series-level gaps -------------------------------------------------
    # A vendor feed that breaks stays broken for a while, so the gap is a
    # *contiguous run* of months drawn once per series - not every third month
    # at random, which any interpolation would silently repair.
    series_code, n_series = _factorize_pairs(hcp, brand)
    panel_start = np.datetime64(profile.panel_start_month, "M")
    month_index = month.astype("datetime64[M]").astype(np.int64) - panel_start.astype(np.int64)

    gapped = generator.random(n_series) < rates.rx_gap_series_rate
    run_length = generator.integers(rates.rx_gap_min_months, rates.rx_gap_max_months + 1, n_series)
    latest = max(profile.months_of_history - rates.rx_gap_max_months, 1)
    start = generator.integers(0, latest, n_series)
    drop = (
        gapped[series_code]
        & (month_index >= start[series_code])
        & (month_index < (start + run_length)[series_code])
    )
    report.record("rx_gap_series", int(gapped.sum()))

    # --- low-coverage sabotage --------------------------------------------
    sabotaged = plan.truth.loc[plan.truth["sabotage_low_coverage"], "event_id"]
    attendance = frames["attendance"]
    victims = attendance.loc[
        attendance["is_verified"] & attendance["event_id"].isin(set(sabotaged)),
        ["hcp_id", "event_id"],
    ]
    if not victims.empty:
        events = plan.events.set_index("event_id")
        victims = victims.assign(
            brand_id=victims["event_id"].map(events["brand_id"]),
            event_date=victims["event_id"].map(events["event_date"]),
        )
        chosen = victims.loc[
            generator.random(victims.shape[0]) < rates.low_coverage_attendee_drop_rate
        ]
        if not chosen.empty:
            cut = pd.DataFrame(
                {
                    "hcp_id": chosen["hcp_id"].to_numpy(),
                    "brand_id": chosen["brand_id"].to_numpy(),
                    "cut_from": chosen["event_date"].to_numpy(),
                }
            ).drop_duplicates(subset=["hcp_id", "brand_id"])
            merged = rx[["hcp_id", "brand_id"]].merge(cut, on=["hcp_id", "brand_id"], how="left")
            cut_from = merged["cut_from"].to_numpy()
            post = ~pd.isna(cut_from) & (month > np.where(pd.isna(cut_from), month, cut_from))
            drop = drop | post
            report.record("rx_rows_dropped_low_coverage", int(post.sum()))

    kept = ~drop
    rx = rx.loc[kept].reset_index(drop=True)
    report.record("rx_rows_dropped", int(drop.sum()))

    # --- small-cell suppression -------------------------------------------
    # Only low-volume cells are suppressed; that is what "small cell" means, and
    # a pipeline that drops suppressed rows therefore drops the *low* tail and
    # biases every mean upward. The defect has to be selective to be dangerous.
    nrx = rx["nrx"].to_numpy(dtype=np.float64)
    eligible = nrx <= rates.suppression_max_nrx
    suppress = eligible & (
        generator.random(rx.shape[0])
        < rates.rx_suppression_rate / max(float(eligible.mean()), 1e-9)
    )
    rx["nrx"] = np.where(suppress, np.nan, nrx)
    rx["trx"] = np.where(suppress, np.nan, rx["trx"].to_numpy(dtype=np.float64))
    rx["suppression_flag"] = suppress
    rx["is_observed"] = ~suppress
    frames["rx_monthly"] = rx
    report.record("rx_rows_suppressed", int(suppress.sum()))


def _factorize_pairs(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, int]:
    """Dense integer code per (left, right) pair, and how many distinct pairs.

    ``pd.factorize`` on a zipped object array would build several million
    Python tuples on the full profile; factorising each side and combining the
    codes arithmetically stays in numpy.
    """
    left_code, _ = pd.factorize(left)
    right_code, right_levels = pd.factorize(right)
    combined = left_code.astype(np.int64) * len(right_levels) + right_code
    code, levels = pd.factorize(combined)
    return code, len(levels)


def _cost_outliers(
    profile: SyntheticProfile,
    frames: dict[str, pd.DataFrame],
    generator: np.random.Generator,
    report: ImperfectionReport,
) -> None:
    """Blow up one cost line on a share of events (plan.md §12.5).

    A single 6x venue invoice moves an event's ROI by more than any plausible
    estimator disagreement, so cost outlier review is not cosmetic - it is part
    of the evidence chain. The multiplier is applied to one line rather than the
    whole event because that is how the error actually arrives: a mis-keyed
    invoice, not a uniformly expensive program.
    """
    rates = profile.imperfections
    costs = frames["event_costs"]
    event_ids = costs["event_id"].unique()
    flagged = set(
        event_ids[generator.random(event_ids.shape[0]) < rates.cost_outlier_event_rate].tolist()
    )
    if not flagged:  # pragma: no cover - rate is never zero in shipped profiles
        report.record("cost_outliers", 0)
        return
    is_flagged = costs["event_id"].isin(flagged).to_numpy()
    # One line per flagged event: the first in the deterministic sort order.
    first_of_event = ~costs["event_id"].duplicated().to_numpy()
    target = is_flagged & first_of_event
    multiplier = generator.uniform(
        rates.cost_outlier_multiplier_lo, rates.cost_outlier_multiplier_hi, int(target.sum())
    )
    amount = costs["amount"].to_numpy(dtype=np.float64).copy()
    amount[target] = np.round(amount[target] * multiplier, 2)
    costs["amount"] = amount
    report.record("cost_outliers", int(target.sum()))
