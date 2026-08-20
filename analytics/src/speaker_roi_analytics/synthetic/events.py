"""Campaigns, events, and the per-event causal truth.

**This module writes ground truth.** ``EventPlan.truth`` becomes
``ground_truth/event_effects.parquet`` and must never be imported by
``speaker_roi_api``, ``speaker_roi_worker`` or any feature builder: it contains
the exact quantity the causal engine is asked to recover.

Event placement is not uniform over the panel, and that is deliberate
(plan.md §12.1). A COMPLETED event needs six pre-period months and three
post-period months to be estimable, so completed events are confined to month
indexes ``[6, T-4]``. Events outside that band would enter the funnel only to be
excluded for ``INSUFFICIENT_PRE_HISTORY`` / ``INSUFFICIENT_POST_COVERAGE``,
which tests the exclusion path but wastes the causal signal. CANCELLED events
are placed anywhere - they keep their invitations and produce zero attendance,
which is precisely the falsification case the evidence funnel must handle.
PROPOSED events sit in the future with no invitations at all, because they are
the input to the forecaster (PLAN_REVIEW F-1, model M3), not to the estimator.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from speaker_roi_core.enums import CampaignStatus, EventFormat, EventStatus

from .config import SyntheticProfile
from .context import month_index_to_date
from .hcps import HcpUniverse
from .taxonomy import Taxonomies, stable_uuid

__all__ = ["EventPlan", "build_events"]

#: Effect classes stored in the truth frame. Not an enum in
#: ``speaker_roi_core`` because the platform never sees them - only the
#: validation suite does.
EFFECT_CLASS_POSITIVE = "POSITIVE"
EFFECT_CLASS_ZERO = "ZERO"
EFFECT_CLASS_NEGATIVE = "NEGATIVE"

_VENUE_CITIES: dict[str, str] = {
    "NE": "Boston",
    "SE": "Atlanta",
    "MW": "Chicago",
    "SW": "Dallas",
    "WEST": "San Francisco",
    "MTN": "Denver",
}


@dataclass(slots=True)
class EventPlan:
    """Campaigns, events, and the per-event truth that pairs with them."""

    campaigns: pd.DataFrame
    events: pd.DataFrame
    truth: pd.DataFrame
    #: campaign_id -> the specialties its events target. Invitation eligibility
    #: is decided against this list.
    campaign_target_specialties: dict[str, tuple[str, ...]]


def _weighted_choice(
    generator: np.random.Generator, labels: tuple[str, ...], weights: dict[str, float], n: int
) -> np.ndarray:
    probabilities = np.array([weights[label] for label in labels], dtype=np.float64)
    probabilities /= probabilities.sum()
    return np.asarray(labels, dtype=object)[generator.choice(len(labels), size=n, p=probabilities)]


def _place_months(
    generator: np.random.Generator,
    profile: SyntheticProfile,
    lo: int,
    hi: int,
    n: int,
) -> np.ndarray:
    """Draw month indexes in ``[lo, hi]`` weighted by calendar seasonality.

    Nobody runs a dinner programme in the week before Christmas. The uneven
    placement also means the cohort-time ATT of PLAN_REVIEW F-10 sees genuinely
    unbalanced cohort sizes, which is the condition under which a naive TWFE
    starts to misbehave - exactly the diagnostic that specification is for.
    """
    indexes = np.arange(lo, hi + 1)
    calendar = (profile.panel_start_month.month - 1 + indexes) % 12 + 1
    weights = np.array(
        [profile.design.month_placement_weights[int(m)] for m in calendar], dtype=np.float64
    )
    weights /= weights.sum()
    return generator.choice(indexes, size=n, p=weights)


def build_events(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    generator: np.random.Generator,
) -> EventPlan:
    """Draw campaigns, then events, then the per-event causal truth."""
    design = profile.design
    effect_params = profile.effect

    brands = taxonomies.brands
    brand_ids = brands["brand_id"].to_numpy()
    brand_tenant = dict(zip(brands["brand_id"], brands["tenant_id"], strict=True))
    brand_code = dict(zip(brands["brand_id"], brands["brand_code"], strict=True))

    primary = taxonomies.specs[0]
    secondary = taxonomies.specs[1]
    tenant_brand_ids = {
        spec.tenant_id: brands.loc[brands["tenant_id"] == spec.tenant_id, "brand_id"].to_numpy()
        for spec in taxonomies.specs
    }

    # --- campaigns ---------------------------------------------------------
    campaign_rows: list[dict[str, object]] = []
    targets: dict[str, tuple[str, ...]] = {}
    for spec, n_campaigns in (
        (primary, profile.n_campaigns_primary),
        (secondary, profile.n_campaigns_secondary),
    ):
        specialties = taxonomies.specialty_codes_by_tenant[spec.tenant_id]
        n_target = max(1, round(len(specialties) * design.campaign_target_specialty_share))
        available = tenant_brand_ids[spec.tenant_id]
        for i in range(n_campaigns):
            bid = str(available[i % len(available)])
            code = f"{spec.tenant_code[:2]}CMP{i + 1:03d}"
            campaign_id = stable_uuid("campaign", spec.tenant_code, code)
            start_month = int(generator.integers(0, max(1, profile.months_of_history - 3)))
            end_month = min(profile.months_of_history - 1, start_month + 5)
            picked = tuple(
                np.asarray(specialties, dtype=object)[
                    generator.choice(len(specialties), size=n_target, replace=False)
                ].tolist()
            )
            targets[campaign_id] = picked
            campaign_rows.append(
                {
                    "tenant_id": spec.tenant_id,
                    "campaign_id": campaign_id,
                    "campaign_code": code,
                    "campaign_name": f"{brand_code[bid].title()} Speaker Series {i + 1}",
                    "brand_id": bid,
                    "status": CampaignStatus.COMPLETED.value
                    if end_month < profile.months_of_history - 2
                    else CampaignStatus.ACTIVE.value,
                    "start_date": month_index_to_date(profile, np.array([start_month]))[0],
                    "end_date": month_index_to_date(profile, np.array([end_month]))[0],
                    "target_specialty_codes": "|".join(picked),
                }
            )
    campaigns = pd.DataFrame(campaign_rows)

    # --- events ------------------------------------------------------------
    counts = (
        (EventStatus.COMPLETED, profile.n_events_completed),
        (EventStatus.CANCELLED, profile.n_events_cancelled),
        (EventStatus.PROPOSED, profile.n_events_proposed),
    )
    blocks: list[pd.DataFrame] = []
    running = 0
    for status, count in counts:
        if status is EventStatus.COMPLETED:
            months = _place_months(
                generator,
                profile,
                profile.completed_event_month_lo,
                profile.completed_event_month_hi,
                count,
            )
        elif status is EventStatus.CANCELLED:
            months = _place_months(generator, profile, 2, profile.months_of_history - 1, count)
        else:
            # Future programs: the forecaster's input, no realised outcome.
            months = generator.integers(
                profile.months_of_history, profile.months_of_history + 6, count
            )
        blocks.append(
            _event_block(
                profile, taxonomies, universe, generator, status, months, running, campaigns
            )
        )
        running += count

    events = pd.concat(blocks, ignore_index=True)
    events = events.sort_values(["tenant_id", "event_date", "event_code"], kind="stable")
    events = events.reset_index(drop=True)

    truth = _draw_truth(profile, taxonomies, events, generator)

    # Sabotage flags live on the truth frame, never on the event record: the
    # platform must *discover* that an event is not reliably estimable from the
    # data, not read a flag that says so (plan.md §12.3).
    sabotage = _draw_sabotage(profile, events, generator)
    truth = truth.merge(sabotage, on="event_id", how="left")

    del brand_ids, brand_tenant, effect_params, tenant_brand_ids
    return EventPlan(
        campaigns=campaigns,
        events=events,
        truth=truth,
        campaign_target_specialties=targets,
    )


def _event_block(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    generator: np.random.Generator,
    status: EventStatus,
    months: np.ndarray,
    ordinal_offset: int,
    campaigns: pd.DataFrame,
) -> pd.DataFrame:
    """One status' worth of events, drawn in a single vectorised pass."""
    design = profile.design
    n = int(months.shape[0])
    primary, secondary = taxonomies.specs

    is_primary = generator.random(n) < profile.primary_tenant_event_share
    tenant_ids = np.where(is_primary, primary.tenant_id, secondary.tenant_id)

    campaign_ids = np.empty(n, dtype=object)
    brand_ids = np.empty(n, dtype=object)
    topics = np.empty(n, dtype=object)
    for spec in taxonomies.specs:
        mask = tenant_ids == spec.tenant_id
        size = int(mask.sum())
        if size == 0:
            continue
        pool = campaigns.loc[campaigns["tenant_id"] == spec.tenant_id]
        picks = generator.integers(0, pool.shape[0], size)
        campaign_ids[mask] = pool["campaign_id"].to_numpy()[picks]
        brand_ids[mask] = pool["brand_id"].to_numpy()[picks]
        tenant_topics = np.asarray(taxonomies.topic_codes_by_tenant[spec.tenant_id], dtype=object)
        topics[mask] = tenant_topics[generator.integers(0, tenant_topics.shape[0], size)]

    formats = _weighted_choice(generator, tuple(EventFormat.values()), design.format_weights, n)
    speaker_tiers = _weighted_choice(
        generator, tuple(design.speaker_tier_weights), design.speaker_tier_weights, n
    )

    # Region is drawn from the *HCP density* of the tenant, so program supply
    # follows prescriber supply rather than being uniform across territories.
    regions = np.empty(n, dtype=object)
    for spec in taxonomies.specs:
        mask = tenant_ids == spec.tenant_id
        size = int(mask.sum())
        if size == 0:
            continue
        lo, hi = universe.tenant_offsets[spec.tenant_id]
        density = np.bincount(
            universe.region_index[lo:hi], minlength=len(taxonomies.region_codes)
        ).astype(np.float64)
        density /= density.sum()
        regions[mask] = np.asarray(taxonomies.region_codes, dtype=object)[
            generator.choice(len(taxonomies.region_codes), size=size, p=density)
        ]

    days = generator.integers(design.event_day_lo, design.event_day_hi + 1, n)
    first_of_month = month_index_to_date(profile, months)
    event_date = first_of_month + (days - 1).astype("timedelta64[D]")

    ordinals = ordinal_offset + np.arange(n)
    event_code = np.array([f"EV{o:06d}" for o in ordinals], dtype=object)
    event_id = np.array(
        [stable_uuid("event", t, c) for t, c in zip(tenant_ids, event_code, strict=True)],
        dtype=object,
    )

    planned = np.maximum(
        design.planned_attendee_min,
        np.round(
            profile.invitations_per_event_mean
            * design.planned_attendee_ratio
            * generator.lognormal(0.0, design.planned_attendee_noise_sigma, n)
        ),
    ).astype(np.int32)

    return pd.DataFrame(
        {
            "tenant_id": tenant_ids,
            "event_id": event_id,
            "event_code": event_code,
            "campaign_id": campaign_ids,
            "brand_id": brand_ids,
            "topic_code": topics,
            "event_format": formats,
            "region_code": regions,
            "venue_city": [_VENUE_CITIES[r] for r in regions],
            "speaker_tier": speaker_tiers,
            "status": status.value,
            "event_date": event_date,
            "event_month_index": months.astype(np.int32),
            "planned_attendees": planned,
        }
    )


def _draw_truth(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    events: pd.DataFrame,
    generator: np.random.Generator,
) -> pd.DataFrame:
    """The hierarchical per-event effect (plan.md §11).

    ``effect_per_attendee = m_global + m_brand + m_topic + m_format + m_region
    + e_event``, then the class assignment overwrites a share of events with
    exactly zero or with a negative draw. The hierarchy matters: an estimator
    that pools all events would be right on average and wrong on every single
    one, and plan.md §12.4 asks for per-event evidence, so the heterogeneity has
    to be real and structured rather than i.i.d. noise.

    The *class* is assigned before the magnitude so that ZERO means exactly
    ``0.0`` - not "a small positive number". A confidence interval covering zero
    is the only correct answer for those events, and a DGP that gave them
    0.03 uplift would let a systematically biased estimator look calibrated.
    """
    params = profile.effect
    n = events.shape[0]

    brand_effect = {
        bid: float(generator.normal(0.0, params.m_brand_sd))
        for bid in taxonomies.brands["brand_id"]
    }
    topic_effect = {
        code: float(generator.normal(0.0, params.m_topic_sd))
        for codes in taxonomies.topic_codes_by_tenant.values()
        for code in codes
    }
    region_effect = {
        code: float(generator.normal(0.0, params.m_region_sd)) for code in taxonomies.region_codes
    }

    base = (
        params.m_global
        + events["brand_id"].map(brand_effect).to_numpy(dtype=np.float64)
        + events["topic_code"].map(topic_effect).to_numpy(dtype=np.float64)
        + events["region_code"].map(region_effect).to_numpy(dtype=np.float64)
        + events["event_format"].map(params.format_offsets).to_numpy(dtype=np.float64)
        + generator.normal(0.0, params.e_event_sd, n)
    )
    effect = np.maximum(base, params.positive_floor)
    effect_class = np.full(n, EFFECT_CLASS_POSITIVE, dtype=object)

    draw = generator.random(n)
    zero_mask = draw < params.zero_effect_share
    negative_mask = (draw >= params.zero_effect_share) & (
        draw < params.zero_effect_share + params.negative_effect_share
    )
    effect[zero_mask] = 0.0
    effect_class[zero_mask] = EFFECT_CLASS_ZERO
    negative_draws = generator.normal(
        params.negative_effect_mean, params.negative_effect_sd, int(negative_mask.sum())
    )
    effect[negative_mask] = np.minimum(negative_draws, -1e-6)
    effect_class[negative_mask] = EFFECT_CLASS_NEGATIVE

    half_life = generator.uniform(params.half_life_lo, params.half_life_hi, n)

    # A cancelled event never happened: no attendance, therefore no effect, and
    # the truth frame has to say so or the falsification test in plan.md §12.6
    # would be comparing against a non-zero target.
    cancelled = events["status"].to_numpy() == EventStatus.CANCELLED.value
    future = events["status"].to_numpy() == EventStatus.PROPOSED.value
    effect[cancelled] = 0.0
    effect_class[cancelled] = EFFECT_CLASS_ZERO

    return pd.DataFrame(
        {
            "tenant_id": events["tenant_id"].to_numpy(),
            "event_id": events["event_id"].to_numpy(),
            "event_month_index": events["event_month_index"].to_numpy(),
            "status": events["status"].to_numpy(),
            "true_effect_per_attendee": np.round(effect, 6),
            "half_life_months": np.round(half_life, 6),
            "effect_class": effect_class,
            "is_realised": ~(cancelled | future),
        }
    )


def _draw_sabotage(
    profile: SyntheticProfile,
    events: pd.DataFrame,
    generator: np.random.Generator,
) -> pd.DataFrame:
    """Mark the events built to fail an evidence gate (plan.md §12.3).

    Half get a starved invitation list, so the treated sample never clears the
    minimum-sample gate; half keep a normal list but have their attendees' post
    period Rx rows shredded, so outcome coverage falls below the threshold. Both
    must resolve to ``EvidenceStatus.NOT_RELIABLY_ESTIMABLE`` - a product that
    silently reports a point estimate for these is the failure mode plan.md §12
    is written to prevent.
    """
    rates = profile.imperfections
    completed = events["status"].to_numpy() == EventStatus.COMPLETED.value
    draw = generator.random(events.shape[0])
    selected = completed & (draw < rates.sabotaged_event_rate)
    coin = generator.random(events.shape[0]) < 0.5
    return pd.DataFrame(
        {
            "event_id": events["event_id"].to_numpy(),
            "sabotage_low_attendance": selected & coin,
            "sabotage_low_coverage": selected & ~coin,
        }
    )
