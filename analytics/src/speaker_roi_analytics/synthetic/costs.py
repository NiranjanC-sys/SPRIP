"""Fully loaded event costs and effective-dated finance assumptions.

ROI is a ratio, and plan.md §12.5 is emphatic that the denominator is where
speaker-program ROI claims usually go wrong: quoting the speaker's honorarium
and omitting venue, catering, travel, AV, materials, vendor management and
compliance review inflates ROI by a factor of two or more. So every event gets
a *line-itemised* cost record, one row per category, and the categories that
apply depend on the format - a VIRTUAL program has AV production and no
catering.

The finance assumptions are deliberately **effective-dated and versioned**.
``contribution_per_nrx`` is revised once mid-window, which means an ROI engine
that joins on brand alone rather than on (brand, date-in-force) will silently
use the wrong number for half the events. That is a real failure mode in
production finance systems and the platform should be made to handle it.

Costs carry no causal information: they are drawn from event characteristics
that are already public in the event record (format, planned attendees,
speaker tier, region), never from the realised effect. A cost that correlated
with the outcome would make ROI look predictive when it is only circular.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from speaker_roi_core.enums import EventFormat, EventStatus, FinanceScenario

from .config import CostParams, SyntheticProfile
from .context import month_index_to_date
from .events import EventPlan
from .taxonomy import Taxonomies, stable_uuid

__all__ = ["build_costs", "build_finance_assumptions"]

#: Formats that put people in a room. Drives which cost categories apply.
_PHYSICAL_FORMATS: frozenset[str] = frozenset(
    {EventFormat.IN_PERSON.value, EventFormat.HYBRID.value}
)
#: Formats with a broadcast leg.
_BROADCAST_FORMATS: frozenset[str] = frozenset(
    {EventFormat.VIRTUAL.value, EventFormat.HYBRID.value}
)


def build_costs(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    plan: EventPlan,
    generator: np.random.Generator,
) -> pd.DataFrame:
    """One row per (event, applicable cost category).

    CANCELLED events keep the costs that were already committed - venue
    deposits, speaker cancellation fees, vendor management - because a program
    that was called off two weeks out is not free, and an ROI engine that treats
    cancelled programs as costless understates portfolio spend. PROPOSED events
    have no actuals at all.
    """
    params = profile.cost
    events = plan.events
    billable = events["status"].to_numpy() != EventStatus.PROPOSED.value
    frame = events.loc[billable].reset_index(drop=True)
    n = frame.shape[0]
    if n == 0:  # pragma: no cover - profiles always have billable events
        return _empty_cost_frame()

    fmt = frame["event_format"].to_numpy()
    planned = frame["planned_attendees"].to_numpy(dtype=np.float64)
    tier = frame["speaker_tier"].to_numpy()
    remoteness = np.array(
        [taxonomies.region_remoteness[str(r)] for r in frame["region_code"]], dtype=np.float64
    )
    cancelled = frame["status"].to_numpy() == EventStatus.CANCELLED.value
    tier_multiplier = np.array(
        [params.speaker_tier_multiplier[str(t)] for t in tier], dtype=np.float64
    )

    currency = {spec.tenant_id: spec.currency for spec in taxonomies.specs}
    blocks: list[pd.DataFrame] = []
    for category, fixed in params.category_fixed.items():
        applies = _category_applies(category, fmt, params)
        if not applies.any():
            continue
        per_attendee = params.category_per_attendee[category]
        amount = fixed + per_attendee * planned
        if category == "SPEAKER_FEE":
            amount = amount * tier_multiplier
        if category == "TRAVEL":
            # A regional program in a remote territory flies people in.
            amount = amount * (1.0 + params.travel_remoteness_loading * (remoteness - 0.5))
        noise = generator.lognormal(0.0, params.amount_noise_sigma, n)
        amount = amount * noise
        # Cancelled: only the committed share survives.
        amount = np.where(
            cancelled, amount * params.cancelled_committed_share.get(category, 0.0), amount
        )
        keep = applies & (amount > 0.0)
        if not keep.any():
            continue
        blocks.append(_cost_block(frame, category, amount, keep, generator, currency))

    costs = pd.concat(blocks, ignore_index=True)
    costs = costs.sort_values(["tenant_id", "event_id", "cost_category"], kind="stable")
    return costs.reset_index(drop=True)


def _category_applies(category: str, fmt: np.ndarray, params: CostParams) -> np.ndarray:
    """Which events carry this category, given their format."""
    if category in params.always_present:
        return np.ones(fmt.shape[0], dtype=bool)
    if category in params.in_person_only:
        return np.isin(fmt, list(_PHYSICAL_FORMATS))
    if category in params.virtual_only:
        return np.isin(fmt, list(_BROADCAST_FORMATS))
    return np.ones(fmt.shape[0], dtype=bool)


def _cost_block(
    frame: pd.DataFrame,
    category: str,
    amount: np.ndarray,
    keep: np.ndarray,
    generator: np.random.Generator,
    currency: dict[str, str],
) -> pd.DataFrame:
    """Materialise one category's rows."""
    idx = np.flatnonzero(keep)
    tenant_ids = frame["tenant_id"].to_numpy()[idx]
    event_ids = frame["event_id"].to_numpy()[idx]
    # Invoices land after the event, on a vendor's own schedule.
    lag = generator.integers(0, 46, idx.shape[0]).astype("timedelta64[D]")
    return pd.DataFrame(
        {
            "tenant_id": tenant_ids,
            "event_cost_id": [stable_uuid("event_cost", str(e), category) for e in event_ids],
            "event_id": event_ids,
            "cost_category": category,
            "amount": np.round(amount[idx], 2),
            "currency_code": [currency[str(t)] for t in tenant_ids],
            "invoice_date": frame["event_date"].to_numpy()[idx] + lag,
            "is_estimate": np.zeros(idx.shape[0], dtype=bool),
        }
    )


def _empty_cost_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tenant_id": pd.Series(dtype=object),
            "event_cost_id": pd.Series(dtype=object),
            "event_id": pd.Series(dtype=object),
            "cost_category": pd.Series(dtype=object),
            "amount": pd.Series(dtype=np.float64),
            "currency_code": pd.Series(dtype=object),
            "invoice_date": pd.Series(dtype="datetime64[ns]"),
            "is_estimate": pd.Series(dtype=bool),
        }
    )


def build_finance_assumptions(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    generator: np.random.Generator,
) -> pd.DataFrame:
    """Effective-dated net contribution per incremental NRx, per brand.

    Two versions per brand: one in force from the start of the panel, one that
    supersedes it mid-window. plan.md §12.5 requires the ROI engine to pick the
    version in force *at the event date* - joining on brand alone gives the
    wrong denominator for every event before the revision, and the error is
    silent, which is why the data has to contain the trap.
    """
    params = profile.cost
    brands = taxonomies.brands
    n_brands = brands.shape[0]
    currency = {spec.tenant_id: spec.currency for spec in taxonomies.specs}
    base = generator.uniform(
        params.contribution_per_nrx_lo, params.contribution_per_nrx_hi, n_brands
    )
    revision_month = profile.months_of_history // 2
    rows: list[pd.DataFrame] = []
    for version, (month, multiplier) in enumerate(
        ((0, 1.0), (revision_month, params.revision_uplift)), start=1
    ):
        effective = month_index_to_date(profile, np.full(n_brands, month))
        for scenario in FinanceScenario:
            factor = params.scenario_multiplier[scenario.value]
            rows.append(
                pd.DataFrame(
                    {
                        "tenant_id": brands["tenant_id"].to_numpy(),
                        "brand_id": brands["brand_id"].to_numpy(),
                        "scenario": scenario.value,
                        "version": version,
                        "effective_from": effective,
                        "net_contribution_per_nrx": np.round(base * multiplier * factor, 2),
                        "currency_code": [currency[str(t)] for t in brands["tenant_id"]],
                    }
                )
            )
    frame = pd.concat(rows, ignore_index=True)
    frame = frame.sort_values(["tenant_id", "brand_id", "scenario", "version"], kind="stable")
    return frame.reset_index(drop=True)
