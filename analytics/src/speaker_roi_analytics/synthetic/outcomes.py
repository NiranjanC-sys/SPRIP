"""The Rx panel, the attendance realisation, and the per-event causal truth.

**This module writes ground truth.** ``PanelResult.truth`` becomes
``ground_truth/event_effects.parquet``; it must never be imported by
``speaker_roi_api``, ``speaker_roi_worker``, or any feature builder.

The treatment effect is additive on the count scale
------------------------------------------------------
plan.md §11 writes the outcome model as ``log lambda = ... + treatment_effect``.
This implementation adds the effect to ``lambda`` instead::

    lambda[h, p, t] = exp(linear_predictor[h, p, t]) + effect_counts[h, b, t]

and here is the argument, because it is the single most consequential deviation
in the factory.

1. The brief states the effect magnitude as "0.35-1.40 **incremental NRx** per
   attendee per month". That is a count, not a log-ratio. Read as a log-scale
   coefficient it would mean ``exp(1.4) = 4x`` prescribing - an absurd program
   effect, and one no evidence gate would ever pass.
2. The brief defines the stored truth as ``true_total_incremental_nrx_90d`` =
   the effect integrated over the post months times the attendee count. That is
   an additive aggregation. A multiplicative DGP has no such closed form: the
   incremental scripts would depend on each HCP's own baseline, so the "total"
   would be a different number for every attendee mix.
3. PLAN_REVIEW F-10 fixes the primary estimator as a cohort-time ATT (levels
   difference-in-differences). A levels DiD estimates an **additive** ATT. If
   the DGP were multiplicative, the estimand and the estimator would disagree by
   construction, the recovery test would fail, and it would fail for a
   definitional reason rather than because the estimator is wrong - exactly the
   failure the brief warns against.

So the DGP is built to match the estimand the platform actually targets. The
multiplicative structure is still fully present in the *confounding*: market
access, competitor pressure, rep calls, seasonality and the latent traits all
enter through ``exp(...)``, so the baseline is heteroscedastic and the naive
comparison is still badly biased.

Sequencing: how the circularity is broken
-----------------------------------------
Attendance depends on pre-event prescribing; prescribing after an event depends
on attendance. The loop resolves this by walking months in order. At iteration
``m`` every month ``<= m`` is already final (an event at month ``m`` moves only
months ``m+1 .. m+6``), so the pre-period features are computable, selection can
run, and the resulting effects are scattered strictly forward. 24 vectorised
iterations for the ``full`` profile - no Python loop ever touches an HCP-month.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import structlog

from speaker_roi_core.enums import (
    AttendanceStatus,
    AttendanceVerificationSource,
    EventFormat,
    EventStatus,
)

from .config import SyntheticProfile
from .context import MarketContext, month_index_to_date
from .events import EventPlan
from .exposure import InvitationSet, SelectionModel, Standardisation, calibrate_intercept, sigmoid
from .hcps import HcpUniverse
from .rng import RngBook, negative_binomial_counts
from .taxonomy import Taxonomies

__all__ = ["PanelResult", "PanelSeries", "build_panel_membership", "simulate_outcomes"]

_LOG = structlog.get_logger(__name__)

#: Verification source by event format. A webinar cannot produce a badge scan.
_VERIFICATION_BY_FORMAT: dict[str, tuple[str, ...]] = {
    EventFormat.IN_PERSON.value: (
        AttendanceVerificationSource.BADGE_SCAN.value,
        AttendanceVerificationSource.SIGN_IN_SHEET.value,
    ),
    EventFormat.ROUNDTABLE.value: (
        AttendanceVerificationSource.SIGN_IN_SHEET.value,
        AttendanceVerificationSource.VENDOR_ATTESTATION.value,
    ),
    EventFormat.HYBRID.value: (
        AttendanceVerificationSource.BADGE_SCAN.value,
        AttendanceVerificationSource.WEBINAR_PLATFORM_LOG.value,
    ),
    EventFormat.VIRTUAL.value: (AttendanceVerificationSource.WEBINAR_PLATFORM_LOG.value,),
    EventFormat.ON_DEMAND.value: (AttendanceVerificationSource.WEBINAR_PLATFORM_LOG.value,),
}


@dataclass(slots=True)
class PanelSeries:
    """The (HCP, product) series index and its static DGP inputs.

    Everything is a flat array of length ``n_series`` so the month loop is pure
    numpy. ``hb`` is the (HCP, brand) grouping the causal analysis works at:
    the Rx panel is at product grain (plan.md §9.5), but a speaker program
    promotes a *brand*, so effects are defined at brand level and split across
    the brand's products in proportion to their baseline share.
    """

    hcp_row: np.ndarray
    product_index: np.ndarray
    brand_index: np.ndarray
    region_index: np.ndarray
    hb_index: np.ndarray
    product_share: np.ndarray
    static_log_level: np.ndarray
    brand_trend: np.ndarray
    access_loading: np.ndarray
    #: [n_hcps, n_brands] -> hb ordinal, or -1 when the HCP is not in that
    #: brand's panel. Dense because n_brands is single digit.
    hcp_brand_lookup: np.ndarray
    n_hb: int
    product_ids: np.ndarray
    brand_ids: np.ndarray
    tenant_ids: np.ndarray

    @property
    def n_series(self) -> int:
        return int(self.hcp_row.shape[0])


@dataclass(slots=True)
class PanelResult:
    """Outputs of the joint simulation."""

    rx_monthly: pd.DataFrame
    attendance: pd.DataFrame
    truth: pd.DataFrame
    diagnostics: dict[str, float] = field(default_factory=dict)


def build_panel_membership(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    generator: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Decide which HCPs appear in which brand's Rx panel.

    A syndicated Rx panel does not cover every prescriber for every molecule.
    Membership is drawn per (HCP, brand) with the profile's base probability,
    modulated by whether the brand's therapeutic area matches the HCP's
    specialty - a rheumatologist is far more likely to show up in an immunology
    panel than in a cardiology one. Every HCP is guaranteed at least one brand,
    so no prescriber is a ghost with zero outcome rows.
    """
    n_hcps = len(universe)
    membership: dict[str, np.ndarray] = {}
    brands = taxonomies.brands
    from .taxonomy import SPECIALTIES

    primary_ta = {s.code: s.primary_ta for s in SPECIALTIES}
    adjacent_ta = {s.code: set(s.adjacent_tas) for s in SPECIALTIES}
    specialty = universe.specialty_code

    per_tenant_any = {spec.tenant_id: np.zeros(n_hcps, dtype=bool) for spec in taxonomies.specs}
    for _, brand in brands.iterrows():
        brand_id = str(brand["brand_id"])
        tenant_id = str(brand["tenant_id"])
        ta = str(brand["therapeutic_area"])
        in_tenant = universe.tenant_id == tenant_id
        fit = np.where(
            np.array([primary_ta.get(str(s)) == ta for s in specialty]),
            1.0,
            np.where(
                np.array([ta in adjacent_ta.get(str(s), set()) for s in specialty]), 0.65, 0.30
            ),
        )
        probability = np.clip(profile.brand_panel_probability * fit * 1.45, 0.0, 0.95)
        draw = generator.random(n_hcps) < probability
        selected = draw & in_tenant
        membership[brand_id] = selected
        per_tenant_any[tenant_id] |= selected

    # Guarantee: every HCP prescribes at least one of their tenant's brands.
    for spec in taxonomies.specs:
        orphan = (universe.tenant_id == spec.tenant_id) & ~per_tenant_any[spec.tenant_id]
        if not orphan.any():
            continue
        tenant_brands = brands.loc[brands["tenant_id"] == spec.tenant_id, "brand_id"].tolist()
        picks = generator.integers(0, len(tenant_brands), int(orphan.sum()))
        orphan_rows = np.flatnonzero(orphan)
        for offset, brand_id in enumerate(tenant_brands):
            membership[brand_id][orphan_rows[picks == offset]] = True
    return membership


def build_series(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    membership: dict[str, np.ndarray],
    generator: np.random.Generator,
) -> PanelSeries:
    """Flatten (HCP, brand, product) panel membership into arrays."""
    outcome = profile.outcome
    latent = profile.latent
    products = taxonomies.products
    brands = taxonomies.brands
    brand_order = {bid: i for i, bid in enumerate(brands["brand_id"].tolist())}
    n_brands = len(brand_order)
    n_hcps = len(universe)

    # Product share within a brand is static: within a brand the only term that
    # varies by product is the constant log offset, so the share never depends on
    # HCP or month. That is what makes a brand-level effect splittable exactly.
    share_by_product: dict[str, float] = {}
    for brand_id, group in products.groupby("brand_id", sort=False):
        offsets = np.array(
            [taxonomies.product_log_offset[str(p)] for p in group["product_id"]], dtype=np.float64
        )
        weights = np.exp(offsets)
        weights /= weights.sum()
        for product_id, weight in zip(group["product_id"], weights, strict=True):
            share_by_product[str(product_id)] = float(weight)
        del brand_id

    hcp_intercept = (
        outcome.intercept + outcome.beta_opportunity_on_intercept * universe.log_opportunity
    )
    affinity_term = outcome.g4_affinity * universe.affinity
    access_loading_by_hcp = outcome.g1_access * (
        1.0 + latent.access_sensitivity_loading * universe.access_sensitivity
    )

    hcp_brand_lookup = np.full((n_hcps, n_brands), -1, dtype=np.int64)
    hcp_rows: list[np.ndarray] = []
    product_idx: list[np.ndarray] = []
    brand_idx: list[np.ndarray] = []
    hb_idx: list[np.ndarray] = []
    shares: list[np.ndarray] = []
    statics: list[np.ndarray] = []
    trends: list[np.ndarray] = []
    product_id_cols: list[np.ndarray] = []
    brand_id_cols: list[np.ndarray] = []
    tenant_id_cols: list[np.ndarray] = []
    next_hb = 0
    product_ordinal = {str(p): i for i, p in enumerate(products["product_id"])}

    for brand_id, group in products.groupby("brand_id", sort=False):
        brand_key = str(brand_id)
        rows = np.flatnonzero(membership[brand_key])
        if rows.size == 0:
            continue
        b_ord = brand_order[brand_key]
        hb_values = next_hb + np.arange(rows.shape[0], dtype=np.int64)
        hcp_brand_lookup[rows, b_ord] = hb_values
        next_hb += rows.shape[0]
        for product_id in group["product_id"]:
            key = str(product_id)
            hcp_rows.append(rows)
            product_idx.append(np.full(rows.shape[0], product_ordinal[key], dtype=np.int64))
            brand_idx.append(np.full(rows.shape[0], b_ord, dtype=np.int64))
            hb_idx.append(hb_values)
            shares.append(np.full(rows.shape[0], share_by_product[key], dtype=np.float64))
            statics.append(
                hcp_intercept[rows]
                + affinity_term[rows]
                + taxonomies.brand_log_level[brand_key]
                + taxonomies.product_log_offset[key]
            )
            trends.append(
                np.full(rows.shape[0], taxonomies.brand_log_trend[brand_key], dtype=np.float64)
            )
            product_id_cols.append(np.full(rows.shape[0], key, dtype=object))
            brand_id_cols.append(np.full(rows.shape[0], brand_key, dtype=object))
            tenant_id_cols.append(universe.tenant_id[rows])

    del generator
    hcp_row = np.concatenate(hcp_rows)
    return _finish_series(
        hcp_row,
        product_idx,
        brand_idx,
        hb_idx,
        shares,
        statics,
        trends,
        universe,
        access_loading_by_hcp,
        hcp_brand_lookup,
        next_hb,
        product_id_cols,
        brand_id_cols,
        tenant_id_cols,
    )


def _finish_series(
    hcp_row: np.ndarray,
    product_idx: list[np.ndarray],
    brand_idx: list[np.ndarray],
    hb_idx: list[np.ndarray],
    shares: list[np.ndarray],
    statics: list[np.ndarray],
    trends: list[np.ndarray],
    universe: HcpUniverse,
    access_loading_by_hcp: np.ndarray,
    hcp_brand_lookup: np.ndarray,
    n_hb: int,
    product_id_cols: list[np.ndarray],
    brand_id_cols: list[np.ndarray],
    tenant_id_cols: list[np.ndarray],
) -> PanelSeries:
    """Concatenate the per-brand blocks into the flat series index."""
    return PanelSeries(
        hcp_row=hcp_row,
        product_index=np.concatenate(product_idx),
        brand_index=np.concatenate(brand_idx),
        region_index=universe.region_index[hcp_row],
        hb_index=np.concatenate(hb_idx),
        product_share=np.concatenate(shares),
        static_log_level=np.concatenate(statics),
        brand_trend=np.concatenate(trends),
        access_loading=access_loading_by_hcp[hcp_row],
        hcp_brand_lookup=hcp_brand_lookup,
        n_hb=n_hb,
        product_ids=np.concatenate(product_id_cols),
        brand_ids=np.concatenate(brand_id_cols),
        tenant_ids=np.concatenate(tenant_id_cols),
    )


# ---------------------------------------------------------------------------
# The joint month loop
# ---------------------------------------------------------------------------


#: Length of the pre-event observable window, in months. The selection model
#: sees the *mean* of the HCP's own prescribing over ``[m - 6, m - 1]`` - the
#: level, deliberately not the slope. See config.SelectionParams deviation 5:
#: a six-point OLS slope on a NegBin series is almost pure sampling noise, so
#: selecting on it manufactures a differential pre-trend and mean reversion
#: that plan.md §12.6 explicitly requires the data *not* to have.
_PRE_WINDOW_MONTHS = 6


@dataclass(slots=True)
class _PassState:
    """Everything one simulation pass produces."""

    nrx: np.ndarray
    lam: np.ndarray
    linear_predictors: np.ndarray
    raw_pre_level: np.ndarray
    raw_rep_calls: np.ndarray
    raw_competing: np.ndarray
    attendance: dict[str, np.ndarray]
    per_event: dict[str, np.ndarray]
    clip_loss_fraction: float


def _prepare_event_features(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    plan: EventPlan,
    invitations: InvitationSet,
    model: SelectionModel,
) -> dict[str, np.ndarray]:
    """Per-invitation quantities that never change between passes."""
    events = plan.events
    specialty = universe.specialty_code
    topic_by_event = events["topic_code"].to_numpy()
    format_by_event = events["event_format"].to_numpy()

    hcp_rows = invitations.hcp_row
    event_rows = invitations.event_row
    topic_fit = np.array(
        [
            taxonomies.topic_fit[(str(s), str(t))]
            for s, t in zip(specialty[hcp_rows], topic_by_event[event_rows], strict=True)
        ],
        dtype=np.float64,
    )
    friction = np.empty(hcp_rows.shape[0], dtype=np.float64)
    for event_format in set(format_by_event.tolist()):
        mask = format_by_event[event_rows] == event_format
        friction[mask] = model.travel_friction(
            str(event_format), universe.remoteness[hcp_rows[mask]]
        )

    n_hcps = len(universe)
    horizon = profile.months_of_history + profile.effect.decay_horizon_months + 1
    invites_per_month = np.zeros((n_hcps, horizon), dtype=np.float64)
    np.add.at(
        invites_per_month,
        (hcp_rows, events["event_month_index"].to_numpy()[event_rows]),
        1.0,
    )
    return {"topic_fit": topic_fit, "friction": friction, "invites_per_month": invites_per_month}


def _simulate_pass(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    plan: EventPlan,
    invitations: InvitationSet,
    market: MarketContext,
    series: PanelSeries,
    model: SelectionModel,
    features: dict[str, np.ndarray],
    intercept: float,
    apply_effects: bool,
    count_rng: np.random.Generator,
    attend_rng: np.random.Generator,
) -> _PassState:
    """Walk the panel month by month, drawing counts then attendance.

    Called two or three times: twice to calibrate the attendance intercept on an
    untreated baseline, once for real. The calibration passes use their own RNG
    streams, so how many calibration iterations we run cannot perturb the
    published dataset.
    """
    outcome = profile.outcome
    selection = profile.selection
    effect_params = profile.effect
    n_months = profile.months_of_history
    n_series = series.n_series

    events = plan.events
    event_status = events["status"].to_numpy()
    event_month = events["event_month_index"].to_numpy()
    brand_order = {bid: i for i, bid in enumerate(taxonomies.brands["brand_id"].tolist())}
    event_brand_ord = np.array([brand_order[str(b)] for b in events["brand_id"]], dtype=np.int64)
    truth_by_event = plan.truth.set_index("event_id")
    effect_size = truth_by_event["true_effect_per_attendee"].to_numpy(dtype=np.float64)
    half_life = truth_by_event["half_life_months"].to_numpy(dtype=np.float64)

    completed_rows: dict[int, list[int]] = {}
    for row in np.flatnonzero(event_status == EventStatus.COMPLETED.value):
        completed_rows.setdefault(int(event_month[row]), []).append(int(row))

    nrx = np.zeros((n_series, n_months), dtype=np.int64)
    lam_store = np.zeros((n_series, n_months), dtype=np.float64)
    nrx_hb = np.zeros((series.n_hb, n_months), dtype=np.float64)
    #: Expected brand-level volume, i.e. ``nrx_hb`` without the count noise. This
    #: is what the invitation and attendance models are allowed to see - see the
    #: comment at the ``pre_level`` computation below for why the distinction is
    #: not cosmetic.
    lam_hb = np.zeros((series.n_hb, n_months), dtype=np.float64)
    effect_hb = np.zeros((series.n_hb, n_months), dtype=np.float64)
    last_attended = np.full((len(universe), len(brand_order)), -10_000, dtype=np.int64)

    clip_loss = 0.0
    lam_total = 0.0
    lp_chunks: list[np.ndarray] = []
    pre_level_chunks: list[np.ndarray] = []
    rep_chunks: list[np.ndarray] = []
    competing_chunks: list[np.ndarray] = []
    att_event: list[np.ndarray] = []
    att_hcp: list[np.ndarray] = []
    att_status: list[np.ndarray] = []
    att_verified: list[np.ndarray] = []
    att_source: list[np.ndarray] = []
    att_month: list[np.ndarray] = []
    per_event_verified = np.zeros(events.shape[0], dtype=np.int64)
    per_event_analysable = np.zeros(events.shape[0], dtype=np.int64)

    season = market.seasonality
    rep_calls = market.rep_calls
    topic_fit_all = features["topic_fit"]
    friction_all = features["friction"]
    invites_per_month = features["invites_per_month"]

    for m in range(n_months):
        linear = (
            series.static_log_level
            + series.brand_trend * (m / 12.0)
            + season[m]
            + series.access_loading * market.access[series.brand_index, series.region_index, m]
            - outcome.g2_competitor * market.competitor[series.brand_index, series.region_index, m]
            + outcome.g3_rep_calls * np.log1p(rep_calls[series.hcp_row, m])
        )
        untreated = np.exp(linear)
        lam_raw = untreated
        if apply_effects:
            lam_raw = lam_raw + effect_hb[series.hb_index, m] * series.product_share
        lam = np.clip(lam_raw, outcome.lambda_floor, outcome.lambda_ceiling)
        clip_loss += float(np.abs(lam - lam_raw).sum())
        lam_total += float(lam_raw.sum())
        lam_store[:, m] = lam
        drawn = negative_binomial_counts(count_rng, lam, outcome.dispersion_phi)
        nrx[:, m] = drawn
        nrx_hb[:, m] = np.bincount(
            series.hb_index, weights=drawn.astype(np.float64), minlength=series.n_hb
        )
        # Deliberately `untreated`, not `lam`: the targeting score must not contain
        # the decaying tail of the HCP's *own previous* program. If it does, every
        # repeat attendee is selected at a locally elevated point on a curve that
        # is on its way down, their post period is mechanically lower than their
        # pre period, and the treated group's trend diverges from the controls'
        # for a reason no covariate can express. Measured, that alone cancelled the
        # entire effect: an expected +0.40 NRx per attendee-month came out at
        # -0.10. Prescriber potential is a property of the practice; this keeps it
        # one.
        lam_hb[:, m] = np.bincount(series.hb_index, weights=untreated, minlength=series.n_hb)

        for row in completed_rows.get(m, ()):
            start, stop = invitations.event_slice[row]
            hcp_rows = invitations.hcp_row[start:stop]
            b_ord = int(event_brand_ord[row])
            hb = series.hcp_brand_lookup[hcp_rows, b_ord]
            in_panel = hb >= 0

            # The pre-period volume the field force is modelled as seeing is the
            # *expected* level, not the realised counts. This is the difference
            # between a DGP a difference-in-differences can identify and one it
            # cannot, and it is worth being explicit about.
            #
            # Selecting on the realised six-month count means selecting partly on
            # that window's noise draw: over-dispersed counts at mu ~ 3.2 have a
            # six-month-mean standard deviation of the same order as the whole
            # cross-sectional spread of mu. Whoever is picked because their recent
            # months happened to run hot then reverts toward their own mean in the
            # post window, and the reversion is *not* shared by the controls,
            # because the controls were not picked that way. That is a violation
            # of parallel trends built into the data - measured at -1.0 to -1.8x
            # the true effect, i.e. large enough to flip the sign of the estimate -
            # so no estimator downstream could recover the truth, and the failure
            # would look like a bug in the estimator rather than in the data.
            #
            # It is also not how targeting works. Field selection runs off
            # prescriber deciles and segment/potential scores: vendor-supplied,
            # smoothed over years and across data sources. Those are estimates of
            # the systematic level, which is exactly `lam_hb`. Matching on the
            # observed pre-period Rx still has real work to do, since the observed
            # counts are a noisy proxy for the same quantity - the SMD stays around
            # 0.8 - but the noise no longer drives who gets treated.
            pre_level = np.zeros(hcp_rows.shape[0], dtype=np.float64)
            if m >= _PRE_WINDOW_MONTHS and in_panel.any():
                window = lam_hb[hb[in_panel], m - _PRE_WINDOW_MONTHS : m]
                pre_level[in_panel] = window.mean(axis=1)
            rep_pre3m = rep_calls[hcp_rows, max(m - 3, 0) : m].mean(axis=1)
            competing = np.maximum(invites_per_month[hcp_rows, m] - 1.0, 0.0)
            recent = (
                (m - last_attended[hcp_rows, b_ord]) <= selection.satiation_window_months
            ).astype(np.float64)

            lp = model.linear_predictor(
                hcp_rows,
                pre_level,
                topic_fit_all[start:stop],
                rep_pre3m,
                friction_all[start:stop],
                competing,
                recent,
            )
            lp_chunks.append(lp)
            pre_level_chunks.append(pre_level)
            rep_chunks.append(rep_pre3m)
            competing_chunks.append(competing)

            probability = sigmoid(lp + intercept)
            attended = attend_rng.random(hcp_rows.shape[0]) < probability
            verified = attended & (
                attend_rng.random(hcp_rows.shape[0]) < selection.verified_fraction
            )
            _record_attendance(
                profile,
                events,
                row,
                m,
                hcp_rows,
                attended,
                verified,
                attend_rng,
                att_event,
                att_hcp,
                att_status,
                att_verified,
                att_source,
                att_month,
            )

            analysable = verified & in_panel
            per_event_verified[row] = int(verified.sum())
            per_event_analysable[row] = int(analysable.sum())
            last_attended[hcp_rows[verified], b_ord] = m

            magnitude = float(effect_size[row])
            if apply_effects and magnitude != 0.0 and analysable.any():
                hb_treated = hb[analysable]
                life = float(half_life[row])
                horizon = min(effect_params.decay_horizon_months, n_months - 1 - m)
                for offset in range(1, horizon + 1):
                    np.add.at(
                        effect_hb,
                        (hb_treated, m + offset),
                        magnitude * float(np.exp(-offset / life)),
                    )

    return _PassState(
        nrx=nrx,
        lam=lam_store,
        linear_predictors=np.concatenate(lp_chunks) if lp_chunks else np.zeros(0),
        raw_pre_level=np.concatenate(pre_level_chunks) if pre_level_chunks else np.zeros(0),
        raw_rep_calls=np.concatenate(rep_chunks) if rep_chunks else np.zeros(0),
        raw_competing=np.concatenate(competing_chunks) if competing_chunks else np.zeros(0),
        attendance={
            "event_row": np.concatenate(att_event) if att_event else np.zeros(0, dtype=np.int64),
            "hcp_row": np.concatenate(att_hcp) if att_hcp else np.zeros(0, dtype=np.int64),
            "status": np.concatenate(att_status) if att_status else np.zeros(0, dtype=object),
            "verified": np.concatenate(att_verified) if att_verified else np.zeros(0, dtype=bool),
            "source": np.concatenate(att_source) if att_source else np.zeros(0, dtype=object),
            "month_index": np.concatenate(att_month) if att_month else np.zeros(0, dtype=np.int64),
        },
        per_event={"verified": per_event_verified, "analysable": per_event_analysable},
        clip_loss_fraction=clip_loss / max(lam_total, 1e-9),
    )


def _record_attendance(
    profile: SyntheticProfile,
    events: pd.DataFrame,
    row: int,
    month: int,
    hcp_rows: np.ndarray,
    attended: np.ndarray,
    verified: np.ndarray,
    generator: np.random.Generator,
    att_event: list[np.ndarray],
    att_hcp: list[np.ndarray],
    att_status: list[np.ndarray],
    att_verified: list[np.ndarray],
    att_source: list[np.ndarray],
    att_month: list[np.ndarray],
) -> None:
    """Emit attendance rows for one event.

    Only attendees, no-shows and cancelled registrations get a row. An invitee
    who simply ignored the invitation has an invitation row and nothing else -
    which is exactly what a vendor attendance file looks like, and it is why the
    cohort builder in plan.md §12.1 has to treat "absent from the attendance
    file" as "did not attend" rather than as missing data.
    """
    selection = profile.selection
    event_format = str(events["event_format"].to_numpy()[row])
    sources = _VERIFICATION_BY_FORMAT[event_format]

    attendee_rows = hcp_rows[attended]
    attendee_verified = verified[attended]
    n_attendees = attendee_rows.shape[0]
    if n_attendees:
        source = np.where(
            attendee_verified,
            np.asarray(sources, dtype=object)[generator.integers(0, len(sources), n_attendees)],
            AttendanceVerificationSource.UNVERIFIED.value,
        )
        att_event.append(np.full(n_attendees, row, dtype=np.int64))
        att_hcp.append(attendee_rows)
        att_status.append(np.full(n_attendees, AttendanceStatus.ATTENDED.value, dtype=object))
        att_verified.append(attendee_verified)
        att_source.append(source)
        att_month.append(np.full(n_attendees, month, dtype=np.int64))

    non_attendee_rows = hcp_rows[~attended]
    n_non = non_attendee_rows.shape[0]
    if not n_non:
        return
    draw = generator.random(n_non)
    no_show = draw < selection.no_show_fraction_of_non_attendees
    cancelled = (draw >= selection.no_show_fraction_of_non_attendees) & (
        draw
        < selection.no_show_fraction_of_non_attendees
        + selection.cancelled_registration_fraction_of_non_attendees
    )
    keep = no_show | cancelled
    if not keep.any():
        return
    status = np.where(
        no_show[keep], AttendanceStatus.NO_SHOW.value, AttendanceStatus.CANCELLED.value
    ).astype(object)
    kept_rows = non_attendee_rows[keep]
    att_event.append(np.full(kept_rows.shape[0], row, dtype=np.int64))
    att_hcp.append(kept_rows)
    att_status.append(status)
    att_verified.append(np.zeros(kept_rows.shape[0], dtype=bool))
    att_source.append(
        np.full(kept_rows.shape[0], AttendanceVerificationSource.UNVERIFIED.value, dtype=object)
    )
    att_month.append(np.full(kept_rows.shape[0], month, dtype=np.int64))


def simulate_outcomes(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    plan: EventPlan,
    invitations: InvitationSet,
    market: MarketContext,
    series: PanelSeries,
    book: RngBook,
) -> PanelResult:
    """Calibrate the attendance intercept, then run the real simulation.

    Three passes. The first two are untreated baselines drawn from the
    ``calibration`` stream: pass one fixes the feature standardisation and a
    provisional intercept, pass two re-solves the intercept against a realistic
    satiation history (the satiation indicator depends on who attended, which
    depends on the intercept - one refinement is enough to converge well inside
    the 26-32% band). The third pass is the published dataset and uses the
    ``outcomes`` and ``attendance`` streams, so the number of calibration
    iterations can never change what is written to disk.
    """
    model = SelectionModel(profile, universe, Standardisation())
    features = _prepare_event_features(profile, taxonomies, universe, plan, invitations, model)

    _LOG.info("synthetic.outcomes.calibration_pass", profile=profile.name, pass_index=1)
    first = _simulate_pass(
        profile,
        taxonomies,
        universe,
        plan,
        invitations,
        market,
        series,
        model,
        features,
        0.0,
        False,
        book.substream("calibration", 1),
        book.substream("calibration", 2),
    )
    standardisation = Standardisation(
        pre_level_mean=float(first.raw_pre_level.mean()),
        pre_level_sd=float(first.raw_pre_level.std()),
        rep_calls_mean=float(first.raw_rep_calls.mean()),
        rep_calls_sd=float(first.raw_rep_calls.std()),
        competing_mean=float(first.raw_competing.mean()),
        competing_sd=float(first.raw_competing.std()),
    )
    model = SelectionModel(profile, universe, standardisation)
    provisional = calibrate_intercept(_restandardise(profile, first, standardisation), profile)

    _LOG.info(
        "synthetic.outcomes.calibration_pass",
        profile=profile.name,
        pass_index=2,
        provisional_intercept=round(provisional, 4),
    )
    second = _simulate_pass(
        profile,
        taxonomies,
        universe,
        plan,
        invitations,
        market,
        series,
        model,
        features,
        provisional,
        False,
        book.substream("calibration", 3),
        book.substream("calibration", 4),
    )
    intercept = calibrate_intercept(second.linear_predictors, profile)

    _LOG.info(
        "synthetic.outcomes.real_pass",
        profile=profile.name,
        intercept=round(intercept, 4),
        n_series=series.n_series,
    )
    final = _simulate_pass(
        profile,
        taxonomies,
        universe,
        plan,
        invitations,
        market,
        series,
        model,
        features,
        intercept,
        True,
        book.stream("outcomes"),
        book.stream("attendance"),
    )
    return _assemble(
        profile, taxonomies, universe, plan, invitations, market, series, book, final, intercept
    )


def _restandardise(
    profile: SyntheticProfile, state: _PassState, standardisation: Standardisation
) -> np.ndarray:
    """Re-express pass-one linear predictors under the frozen standardisation.

    Pass one runs with the identity standardisation because the constants are
    not known until it finishes. Rather than re-simulate, the three standardised
    terms are simply substituted: the predictor is linear in them, so this is
    exact, not an approximation.
    """
    params = profile.selection
    identity = Standardisation()
    correction = (
        params.beta_pre6m_nrx_level
        * (
            standardisation.z_pre_level(state.raw_pre_level)
            - identity.z_pre_level(state.raw_pre_level)
        )
        + params.beta_rep_calls_pre3m
        * (
            standardisation.z_rep_calls(state.raw_rep_calls)
            - identity.z_rep_calls(state.raw_rep_calls)
        )
        + params.beta_competing_events
        * (
            standardisation.z_competing(state.raw_competing)
            - identity.z_competing(state.raw_competing)
        )
    )
    return state.linear_predictors + correction


def _assemble(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    plan: EventPlan,
    invitations: InvitationSet,
    market: MarketContext,
    series: PanelSeries,
    book: RngBook,
    state: _PassState,
    intercept: float,
) -> PanelResult:
    """Turn the simulation arrays into the gold frames and the truth frame."""
    rx = _build_rx_frame(profile, taxonomies, universe, market, series, state, book)
    attendance = _build_attendance_frame(profile, universe, plan, state, book)
    truth = _build_truth_frame(profile, plan, state)

    invited_completed = _invited_to_completed(plan, invitations)
    verified_total = int(state.per_event["verified"].sum())
    rate = verified_total / max(invited_completed, 1)
    overlapping = _overlapping_exposure_rate(plan, attendance, profile)
    nrx_values = state.nrx.astype(np.float64)
    diagnostics = {
        "verified_attendance_rate": rate,
        "attendance_intercept": intercept,
        "lambda_clip_loss_fraction": state.clip_loss_fraction,
        "overlapping_exposure_rate": overlapping,
        "nrx_variance_over_mean": float(nrx_values.var() / max(nrx_values.mean(), 1e-9)),
        "observed_zero_share": float((state.nrx == 0).mean()),
        "invited_to_completed": float(invited_completed),
    }
    _LOG.info("synthetic.outcomes.done", profile=profile.name, **diagnostics)
    return PanelResult(rx_monthly=rx, attendance=attendance, truth=truth, diagnostics=diagnostics)


def _invited_to_completed(plan: EventPlan, invitations: InvitationSet) -> int:
    """Denominator for the attendance rate: invitations to COMPLETED events.

    Cancelled events keep their invitations but can produce no attendance, so
    including them would mechanically depress the rate below the mandated band
    for a reason that has nothing to do with the selection model.
    """
    completed = plan.events["status"].to_numpy() == EventStatus.COMPLETED.value
    return int(completed[invitations.event_row].sum())


def _build_rx_frame(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    market: MarketContext,
    series: PanelSeries,
    state: _PassState,
    book: RngBook,
) -> pd.DataFrame:
    """Materialise the Rx panel, one tenant-brand chunk at a time.

    Chunking is a memory discipline, not an optimisation: plan.md §11 requires
    the ``full`` profile to generate inside a normal worker's footprint, and
    holding a million-row frame *plus* its intermediate refill and competitor
    draws simultaneously is what pushes peak RSS over the line. Each chunk is
    reduced to its final dtypes before the next one is built.
    """
    outcome = profile.outcome
    n_months = profile.months_of_history
    months = month_index_to_date(profile, np.arange(n_months))
    brand_ids = taxonomies.brands["brand_id"].tolist()
    chunks: list[pd.DataFrame] = []

    for chunk_index, brand_id in enumerate(brand_ids):
        rows = np.flatnonzero(series.brand_ids == brand_id)
        if rows.size == 0:
            continue
        generator = book.substream("outcomes", 1000 + chunk_index)
        nrx = state.nrx[rows]
        lam = state.lam[rows]

        # Refills follow the last three months of new starts: a chronic therapy
        # generates repeat scripts long after the new-start decision.
        cumulative = np.cumsum(nrx, axis=1, dtype=np.float64)
        lagged = np.concatenate([np.zeros((rows.shape[0], 3)), cumulative[:, :-3]], axis=1)[
            :, :n_months
        ]
        window = np.minimum(np.arange(1, n_months + 1), 3).astype(np.float64)
        rolling = (cumulative - lagged) / window
        refills = generator.poisson(outcome.refill_rate * rolling)
        trx = nrx + refills

        competitor_index = market.competitor[
            series.brand_index[rows][:, None],
            series.region_index[rows][:, None],
            np.arange(n_months)[None, :],
        ]
        competitor_mean = lam * np.exp(
            outcome.competitor_log_offset
            + outcome.competitor_index_loading * (competitor_index - 0.5)
        )
        competitor = negative_binomial_counts(
            generator, competitor_mean, outcome.competitor_dispersion_phi
        )

        n_rows = rows.shape[0]
        chunks.append(
            pd.DataFrame(
                {
                    "tenant_id": np.repeat(series.tenant_ids[rows], n_months),
                    "hcp_id": np.repeat(
                        universe.frame["hcp_id"].to_numpy()[series.hcp_row[rows]], n_months
                    ),
                    "brand_id": np.repeat(series.brand_ids[rows], n_months),
                    "product_id": np.repeat(series.product_ids[rows], n_months),
                    "month": np.tile(months, n_rows),
                    "nrx": nrx.ravel().astype(np.int32),
                    "trx": trx.ravel().astype(np.int32),
                    "competitor_trx": competitor.ravel().astype(np.int32),
                    "is_observed": True,
                    "suppression_flag": False,
                }
            )
        )
        del nrx, lam, refills, trx, competitor, competitor_mean, competitor_index
    return pd.concat(chunks, ignore_index=True)


def _build_attendance_frame(
    profile: SyntheticProfile,
    universe: HcpUniverse,
    plan: EventPlan,
    state: _PassState,
    book: RngBook,
) -> pd.DataFrame:
    """Materialise the attendance frame."""
    selection = profile.selection
    generator = book.substream("attendance", 9001)
    records = state.attendance
    event_rows = records["event_row"]
    hcp_rows = records["hcp_row"]
    n = event_rows.shape[0]
    events = plan.events

    duration = np.clip(
        generator.normal(selection.duration_mean_minutes, selection.duration_sd_minutes, n),
        selection.duration_min_minutes,
        selection.duration_max_minutes,
    ).round(0)
    attended = records["status"] == AttendanceStatus.ATTENDED.value
    duration_col = np.where(attended, duration, np.nan)

    return pd.DataFrame(
        {
            "tenant_id": events["tenant_id"].to_numpy()[event_rows],
            "event_id": events["event_id"].to_numpy()[event_rows],
            "hcp_id": universe.frame["hcp_id"].to_numpy()[hcp_rows],
            "attendance_status": records["status"],
            "verification_source": records["source"],
            "is_verified": records["verified"],
            "attended_on": events["event_date"].to_numpy()[event_rows],
            "duration_minutes": duration_col,
        }
    )


def _build_truth_frame(
    profile: SyntheticProfile, plan: EventPlan, state: _PassState
) -> pd.DataFrame:
    """Attach the realised attendee counts and the 90-day incremental total.

    ``true_total_incremental_nrx_90d`` is deliberately computed from the
    *realised* analysable attendee set and the *actual* decay integral over post
    months +1, +2, +3 - not from planned attendance and not from a closed-form
    approximation. That is precisely the quantity the causal engine is asked to
    recover (plan.md §12.4), so any other definition would make the recovery
    test fail for a bookkeeping reason instead of a statistical one.

    "Analysable" means verified *and* present in that brand's Rx panel. An
    attendee with no outcome series contributes no observable incremental
    scripts, so counting them would set a target the estimator could never hit.
    """
    truth = plan.truth.copy()
    params = profile.effect
    half_life = truth["half_life_months"].to_numpy(dtype=np.float64)
    offsets = np.arange(1, params.post_window_months + 1, dtype=np.float64)
    decay_sum = np.exp(-offsets[None, :] / half_life[:, None]).sum(axis=1)

    truth["verified_attendee_count"] = state.per_event["verified"]
    truth["analysable_attendee_count"] = state.per_event["analysable"]
    truth["decay_sum_90d"] = np.round(decay_sum, 6)
    truth["true_total_incremental_nrx_90d"] = np.round(
        truth["true_effect_per_attendee"].to_numpy(dtype=np.float64)
        * decay_sum
        * truth["analysable_attendee_count"].to_numpy(dtype=np.float64),
        6,
    )
    return truth


def _overlapping_exposure_rate(
    plan: EventPlan, attendance: pd.DataFrame, profile: SyntheticProfile
) -> float:
    """Share of verified attendances with another same-brand one within 90 days.

    plan.md §12.1 excludes these from the treated cohort
    (``ExclusionReason.OVERLAPPING_EXPOSURE``): a second program inside the
    outcome window makes the attributed effect un-separable. The rate has to be
    non-trivial for that path to be exercised, and small enough that it does not
    gut the cohort.
    """
    verified = attendance.loc[attendance["is_verified"]]
    if verified.empty:
        return 0.0
    brands = plan.events.set_index("event_id")["brand_id"]
    day = verified["attended_on"].to_numpy().astype("datetime64[D]").astype(np.int64)
    frame = pd.DataFrame(
        {
            "hcp_id": verified["hcp_id"].to_numpy(),
            "brand_id": verified["event_id"].map(brands).to_numpy(),
            "day": day,
        }
    ).sort_values(["hcp_id", "brand_id", "day"], kind="stable")
    grouped = frame.groupby(["hcp_id", "brand_id"], sort=False)["day"]
    # 90 days, measured on the actual programme dates rather than month indexes:
    # plan.md §12.1 defines the contamination window in days, and two programmes
    # in adjacent calendar months can be 5 days or 55 days apart.
    window = float(profile.effect.post_window_months * 30)
    gap_next = grouped.shift(-1) - frame["day"]
    gap_prev = frame["day"] - grouped.shift(1)
    overlapping = ((gap_next <= window) | (gap_prev <= window)).fillna(value=False)
    return float(overlapping.mean())
