"""Invitations and the attendance selection model - where the confounding lives.

This is the module that decides whether the whole exercise is worth running.
If attendance were random, a difference in means would be unbiased, the
propensity model would be decoration, and plan.md §12.6's sensitivity suite
would have nothing to bound. So attendance is driven by exactly the traits that
also drive prescribing::

    logit P(attend | invited) =
          t0
        + 0.80 * z(latent_opportunity)          # latent, and drives baseline Rx
        + 0.65 * z(latent_affinity)             # latent, and drives baseline Rx
        + 0.55 * z(pre6m_nrx_level)             # OBSERVABLE - matching's job
        + 0.40 * topic_fit(specialty, topic)
        + 0.30 * z(prior_engagement_count)
        + 0.25 * z(rep_calls_pre3m)
        - 0.70 * travel_friction(format, region)
        - 0.20 * z(same_month_competing_events)
        - 1.75 * recently_attended_same_brand    # see config.py note 3

Two invariants are load-bearing and are asserted by the model-validation suite:

1. **Every feature is knowable strictly before the event date.** ``pre6m`` means
   months ``[m-6, m-1]``; the event month itself is excluded. A single
   post-event quantity in this list would leak the outcome into the treatment
   assignment and quietly make the recovered ATT look perfect.
2. **The two latent terms are never written to any frame the platform reads.**
   They are the residual confounding that survives matching. Their combined
   weight (0.80 + 0.65) is deliberately larger than the observable level term
   (0.55), so a matching-only analysis stays visibly biased and the sensitivity
   bound has real work to do.

The intercept ``t0`` is not hand-tuned; it is solved by bisection so the
realised verified-attendance rate lands inside the mandated 26-32% band.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from speaker_roi_core.enums import EventStatus

from .config import SyntheticProfile
from .events import EventPlan
from .hcps import HcpUniverse
from .rng import gumbel_top_k
from .taxonomy import Taxonomies

__all__ = [
    "InvitationSet",
    "SelectionModel",
    "Standardisation",
    "build_invitations",
    "calibrate_intercept",
    "sigmoid",
]


@dataclass(slots=True)
class InvitationSet:
    """Invitations in event order, plus the array views the loop needs.

    ``event_slice`` maps an event's row position in ``events`` to the
    ``[start, stop)`` span of its invitation rows, so the month loop can address
    one event's invitees without a groupby.
    """

    frame: pd.DataFrame
    hcp_row: np.ndarray
    event_row: np.ndarray
    is_eligible: np.ndarray
    event_slice: dict[int, tuple[int, int]]


def _sample_counts(generator: np.random.Generator, profile: SyntheticProfile, n: int) -> np.ndarray:
    """Invitation-list sizes: NegBin around the profile mean, clipped.

    plan.md §11 says "NegBin around 40". PLAN_REVIEW F-2 simultaneously demands
    >= 62,000 verified attendance rows from ~4,300 completed events at a 26-32%
    attendance rate, which needs >= 48 invitations per completed event. The two
    cannot both hold; the row minimums are the binding contract, so the mean is
    raised to ``profile.invitations_per_event_mean`` and the deviation is
    recorded in ``docs/synthetic_data.md``.
    """
    mean = profile.invitations_per_event_mean
    # Dispersion chosen so the sd is roughly a third of the mean - list sizes
    # vary with venue and budget, but not by an order of magnitude.
    phi = 9.0
    p = phi / (phi + mean)
    counts = generator.negative_binomial(phi, p, n)
    return np.clip(
        counts, profile.invitations_per_event_min, profile.invitations_per_event_max
    ).astype(np.int64)


def build_invitations(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    plan: EventPlan,
    panel_membership: dict[str, np.ndarray],
    generator: np.random.Generator,
) -> InvitationSet:
    """Draw the invitation list for every event that has one.

    COMPLETED and CANCELLED events both get invitations - a program that was
    cancelled two weeks out had already gone to invite, and keeping those rows
    is what makes the cancelled-event falsification test in plan.md §12.6
    possible. PROPOSED (future) events get none.

    Invitations are drawn in event-date order so the cooldown penalty can see
    what each HCP has already been invited to. This is the only place in the
    generator that is order-dependent, and the order is a deterministic sort, so
    it stays reproducible.
    """
    design = profile.design
    events = plan.events
    has_invitations = events["status"].to_numpy() != EventStatus.PROPOSED.value
    rows = np.flatnonzero(has_invitations)
    counts = _sample_counts(generator, profile, rows.shape[0])

    # Sabotaged "too few attendees" events get a starved list instead.
    sabotage = plan.truth.set_index("event_id")["sabotage_low_attendance"]
    starved = events["event_id"].map(sabotage).fillna(False).to_numpy()[rows]
    counts = np.where(starved, profile.imperfections.low_attendance_invitation_count, counts)
    exception_events = generator.random(rows.shape[0]) < design.invite_cooldown_exception_rate

    z_opportunity = _zscore(universe.log_opportunity)
    z_prior = _zscore(universe.prior_engagement)
    n_hcps = len(universe)
    #: Days-since-last-invitation trackers, initialised far in the past. The
    #: second is per (HCP, brand) and enforces the compliance-style cap on how
    #: often one prescriber is engaged on one brand.
    last_invited_day = np.full(n_hcps, -1e9, dtype=np.float64)
    brand_ordinal = {bid: i for i, bid in enumerate(taxonomies.brands["brand_id"].tolist())}
    last_brand_day = np.full((n_hcps, len(brand_ordinal)), -1e9, dtype=np.float64)
    event_day = (
        events["event_date"].to_numpy().astype("datetime64[D]").astype(np.int64).astype(np.float64)
    )

    specialty = universe.specialty_code
    region = universe.region_code
    tenant_of_hcp = universe.tenant_id

    chunks_hcp: list[np.ndarray] = []
    chunks_event: list[np.ndarray] = []
    chunks_eligible: list[np.ndarray] = []
    event_slice: dict[int, tuple[int, int]] = {}
    cursor = 0

    topic_fit = taxonomies.topic_fit
    campaign_targets = plan.campaign_target_specialties
    event_tenant = events["tenant_id"].to_numpy()
    event_topic = events["topic_code"].to_numpy()
    event_region = events["region_code"].to_numpy()
    event_brand = events["brand_id"].to_numpy()
    event_campaign = events["campaign_id"].to_numpy()

    tenant_masks = {spec.tenant_id: (tenant_of_hcp == spec.tenant_id) for spec in taxonomies.specs}
    tenant_rows = {tid: np.flatnonzero(mask) for tid, mask in tenant_masks.items()}
    # topic_fit per (tenant HCP block, topic) is reused across events, so it is
    # cached rather than recomputed for each of 5,000 invitation draws.
    fit_cache: dict[tuple[str, str], np.ndarray] = {}

    for order, row in enumerate(rows):
        tenant = str(event_tenant[row])
        candidate = tenant_rows[tenant]
        topic = str(event_topic[row])
        key = (tenant, topic)
        fit = fit_cache.get(key)
        if fit is None:
            fit = np.array(
                [topic_fit[(str(s), topic)] for s in specialty[candidate]], dtype=np.float64
            )
            fit_cache[key] = fit

        brand_key = str(event_brand[row])
        b_ord = brand_ordinal[brand_key]
        in_panel = panel_membership[brand_key][candidate].astype(np.float64)
        same_region = (region[candidate] == event_region[row]).astype(np.float64)
        recency = np.clip(
            1.0 - (event_day[row] - last_invited_day[candidate]) / design.invite_cooldown_days,
            0.0,
            1.0,
        )
        blocked = (
            event_day[row] - last_brand_day[candidate, b_ord]
        ) < design.invite_brand_cooldown_days
        if exception_events[order]:
            blocked = np.zeros_like(blocked)
        brand_recency = blocked.astype(np.float64)
        log_weights = (
            design.invite_w_same_region * same_region
            + design.invite_w_topic_fit * fit
            + design.invite_w_opportunity * z_opportunity[candidate]
            + design.invite_w_prior_engagement * z_prior[candidate]
            + design.invite_w_in_brand_panel * in_panel
            - design.invite_cooldown_penalty * recency
            - design.invite_brand_cooldown_penalty * brand_recency
        )
        picked_local = gumbel_top_k(generator, log_weights, int(counts[order]))
        picked = candidate[picked_local]
        last_invited_day[picked] = event_day[row]
        last_brand_day[picked, b_ord] = event_day[row]

        targets = campaign_targets[str(event_campaign[row])]
        eligible = np.isin(specialty[picked], np.asarray(targets, dtype=object))
        # A documented share of invitations deliberately go outside the campaign's
        # target specialties; the cohort builder must drop them for
        # ExclusionReason.INELIGIBLE_SPECIALTY rather than silently include them.
        chunks_hcp.append(picked)
        chunks_event.append(np.full(picked.shape[0], row, dtype=np.int64))
        chunks_eligible.append(eligible)
        event_slice[int(row)] = (cursor, cursor + picked.shape[0])
        cursor += picked.shape[0]

    hcp_row = np.concatenate(chunks_hcp)
    event_row = np.concatenate(chunks_event)
    is_eligible = np.concatenate(chunks_eligible)

    frame = _invitation_frame(profile, universe, events, hcp_row, event_row, is_eligible, generator)
    return InvitationSet(
        frame=frame,
        hcp_row=hcp_row,
        event_row=event_row,
        is_eligible=is_eligible,
        event_slice=event_slice,
    )


def _invitation_frame(
    profile: SyntheticProfile,
    universe: HcpUniverse,
    events: pd.DataFrame,
    hcp_row: np.ndarray,
    event_row: np.ndarray,
    is_eligible: np.ndarray,
    generator: np.random.Generator,
) -> pd.DataFrame:
    """Materialise the gold invitation frame."""
    design = profile.design
    n = hcp_row.shape[0]
    channels = list(design.invitation_channel_weights)
    probabilities = np.array(list(design.invitation_channel_weights.values()))
    probabilities /= probabilities.sum()
    channel = np.asarray(channels, dtype=object)[
        generator.choice(len(channels), size=n, p=probabilities)
    ]
    lead = generator.integers(design.invitation_lead_days_lo, design.invitation_lead_days_hi + 1, n)
    invited_on = events["event_date"].to_numpy()[event_row] - lead.astype("timedelta64[D]")
    return pd.DataFrame(
        {
            "tenant_id": events["tenant_id"].to_numpy()[event_row],
            "event_id": events["event_id"].to_numpy()[event_row],
            "hcp_id": universe.frame["hcp_id"].to_numpy()[hcp_row],
            "invitation_channel": channel,
            "invited_on": invited_on,
            "is_target_specialty": is_eligible,
        }
    )


def _zscore(values: np.ndarray) -> np.ndarray:
    sd = float(np.std(values))
    if sd < 1e-12:
        return np.zeros_like(values, dtype=np.float64)
    return (values - float(np.mean(values))) / sd


@dataclass(slots=True)
class Standardisation:
    """Frozen (mean, sd) pairs for the selection features.

    Frozen, and estimated once on the untreated baseline, because a z-score
    computed *per event* would be a different transformation for every event -
    the coefficients would then no longer mean what the docstring says they
    mean, and a small event's single high-volume invitee would look like a
    +3 sigma outlier purely because his event was small.
    """

    pre_level_mean: float = 0.0
    pre_level_sd: float = 1.0
    rep_calls_mean: float = 0.0
    rep_calls_sd: float = 1.0
    competing_mean: float = 0.0
    competing_sd: float = 1.0

    def z_pre_level(self, values: np.ndarray) -> np.ndarray:
        return (values - self.pre_level_mean) / max(self.pre_level_sd, 1e-9)

    def z_rep_calls(self, values: np.ndarray) -> np.ndarray:
        return (values - self.rep_calls_mean) / max(self.rep_calls_sd, 1e-9)

    def z_competing(self, values: np.ndarray) -> np.ndarray:
        return (values - self.competing_mean) / max(self.competing_sd, 1e-9)


class SelectionModel:
    """The attendance logit, minus its intercept.

    Splitting the intercept out is what makes calibration cheap: the linear
    predictor is computed once during the pre-pass, and the bisection over
    ``t0`` then only re-evaluates ``sigmoid(t0 + lp)`` on a stored vector rather
    than regenerating the dataset.
    """

    __slots__ = (
        "_friction_by_format",
        "_params",
        "_z_affinity",
        "_z_opportunity",
        "_z_prior",
        "standardisation",
    )

    def __init__(
        self,
        profile: SyntheticProfile,
        universe: HcpUniverse,
        standardisation: Standardisation,
    ) -> None:
        self._params = profile.selection
        self.standardisation = standardisation
        self._z_opportunity = _zscore(universe.log_opportunity)
        self._z_affinity = _zscore(universe.affinity)
        self._z_prior = _zscore(universe.prior_engagement)
        self._friction_by_format = dict(self._params.format_travel_friction)

    def travel_friction(self, event_format: str, remoteness: np.ndarray) -> np.ndarray:
        """Friction in [0, 1]: format cost amplified by how far people travel."""
        base = self._friction_by_format[event_format]
        loading = self._params.travel_friction_remoteness_loading
        return np.clip(base * (1.0 + loading * (remoteness - 0.5)), 0.0, 1.0)

    def linear_predictor(
        self,
        hcp_rows: np.ndarray,
        pre6m_nrx_level: np.ndarray,
        topic_fit: np.ndarray,
        rep_calls_pre3m: np.ndarray,
        travel_friction: np.ndarray,
        competing_events: np.ndarray,
        recently_attended: np.ndarray,
    ) -> np.ndarray:
        """``logit P(attend) - t0`` for one event's invitee list.

        Every argument is a pre-event quantity. ``pre6m_nrx_level`` is the mean
        of the HCP's own prescribing over months ``[m-6, m-1]``; the event month
        is excluded on both sides of the model, so nothing that happens at or
        after the program can influence who attended it.
        """
        params = self._params
        std = self.standardisation
        return (
            params.beta_latent_opportunity * self._z_opportunity[hcp_rows]
            + params.beta_latent_affinity * self._z_affinity[hcp_rows]
            + params.beta_pre6m_nrx_level * std.z_pre_level(pre6m_nrx_level)
            + params.beta_topic_fit * topic_fit
            + params.beta_prior_engagement * self._z_prior[hcp_rows]
            + params.beta_rep_calls_pre3m * std.z_rep_calls(rep_calls_pre3m)
            + params.beta_travel_friction * travel_friction
            + params.beta_competing_events * std.z_competing(competing_events)
            + params.beta_recent_attendance_satiation * recently_attended
        )


def sigmoid(values: np.ndarray) -> np.ndarray:
    """Numerically stable logistic."""
    out = np.empty_like(values, dtype=np.float64)
    positive = values >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exp_negative = np.exp(values[~positive])
    out[~positive] = exp_negative / (1.0 + exp_negative)
    return out


def calibrate_intercept(
    linear_predictors: np.ndarray,
    profile: SyntheticProfile,
) -> float:
    """Solve ``t0`` so the expected *verified* attendance rate hits the target.

    ``mean(sigmoid(t0 + lp)) * verified_fraction`` is monotone increasing in
    ``t0``, so bisection converges unconditionally - no starting guess, no
    tuning, and the same answer on every machine. The multiplication by
    ``verified_fraction`` matters: plan.md §12.1 counts an attendee as treated
    only when the attendance is *verifiable*, so the 26-32% band is a band on
    verified attendance, not on raw sign-ins.
    """
    params = profile.selection
    target = params.target_verified_attendance_rate
    lo, hi = params.intercept_search_lo, params.intercept_search_hi

    def realised(t0: float) -> float:
        return float(np.mean(sigmoid(linear_predictors + t0))) * params.verified_fraction

    while hi - lo > params.intercept_search_tol:
        mid = 0.5 * (lo + hi)
        if realised(mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
