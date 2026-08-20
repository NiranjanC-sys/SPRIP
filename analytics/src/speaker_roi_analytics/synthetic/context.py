"""Market factors and marketing activity - the observable confounders.

Everything in this module exists to make the naive estimator wrong for
*realistic* reasons, and to give the propensity model something real to adjust
for (plan.md §11: "market access shifts, competitor pressure, seasonality and
marketing activity must move the outcome independently of the programs").

Two design choices matter.

**The market indices are AR(1), not white noise.** A formulary position does not
resample itself every month; it drifts, and a brand that gains access in March
keeps it. A smooth confounder is far more dangerous than a noisy one - a naive
pre/post comparison averages white noise away but inherits the whole level shift
of a smooth one. If the DGP used i.i.d. shocks, the "naive estimator is biased"
test would pass for the wrong reason.

**Marketing activity is driven by ``latent_opportunity``.** Field effort chases
prescribing potential, which means rep calls are a *confounder*: they raise
prescribing (``g3_rep_calls`` in the outcome model) and they correlate with the
same latent trait that raises attendance. Unlike the latent traits themselves,
rep calls are observable, so this is the confounding path the propensity model
is expected to close. Both paths must exist for plan.md §12.6's sensitivity
analysis to be a meaningful exercise rather than theatre.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .config import SyntheticProfile
from .hcps import HcpUniverse
from .taxonomy import Taxonomies

__all__ = [
    "MarketContext",
    "apply_program_halo",
    "build_context",
    "month_index_to_date",
    "seasonality_curve",
]


def month_index_to_date(profile: SyntheticProfile, month_index: np.ndarray) -> np.ndarray:
    """Map 0-based month indexes to first-of-month ``datetime64[ns]`` values."""
    start = profile.panel_start_month
    total = start.year * 12 + (start.month - 1) + np.asarray(month_index, dtype=np.int64)
    years = total // 12
    months = total % 12 + 1
    return pd.to_datetime({"year": years, "month": months, "day": np.ones_like(years)}).to_numpy()


def seasonality_curve(profile: SyntheticProfile, n_months: int) -> np.ndarray:
    """``s(t)`` from plan.md §11, evaluated on *calendar* month, not panel index.

    Anchoring on the calendar month rather than the panel offset means the smoke
    and full profiles share the same seasonal shape at the same wall-clock date,
    so a seasonal artefact seen in one profile is reproducible in the other.
    """
    start = profile.panel_start_month
    calendar = (start.month - 1 + np.arange(n_months)) % 12
    outcome = profile.outcome
    return outcome.seasonality_sin_amp * np.sin(
        2.0 * np.pi * calendar / 12.0
    ) + outcome.seasonality_cos_amp * np.cos(4.0 * np.pi * calendar / 12.0)


def _ar1_walk(
    generator: np.random.Generator,
    n_series: int,
    n_months: int,
    long_run_mean: np.ndarray,
    rho: float,
    innovation_sd: float,
    lo: float,
    hi: float,
    drift_per_month: float = 0.0,
) -> np.ndarray:
    """Mean-reverting AR(1) walks, clipped to a plausible band.

    ``x[t] = mean + rho * (x[t-1] - mean) + eps``, started at the stationary
    distribution so there is no burn-in artefact in the first months - which
    would otherwise show up as a spurious trend in the earliest pre-period.
    """
    stationary_sd = innovation_sd / np.sqrt(max(1.0 - rho**2, 1e-9))
    out = np.empty((n_series, n_months), dtype=np.float64)
    out[:, 0] = long_run_mean + generator.normal(0.0, stationary_sd, n_series)
    shocks = generator.normal(0.0, innovation_sd, (n_series, n_months))
    for t in range(1, n_months):
        drifted = long_run_mean + drift_per_month * t
        out[:, t] = drifted + rho * (out[:, t - 1] - drifted) + shocks[:, t]
    return np.clip(out, lo, hi)


@dataclass(slots=True)
class MarketContext:
    """Market indices and per-HCP marketing activity, in array form.

    ``access`` and ``competitor`` are indexed ``[brand_ordinal, region_ordinal,
    month]``; the marketing arrays are ``[hcp_row, month]``. Arrays rather than
    long frames because the outcome model reads them once per (brand, month)
    slice and a pandas join per slice would dominate the runtime.
    """

    brand_ids: tuple[str, ...]
    brand_ordinal: dict[str, int]
    access: np.ndarray
    competitor: np.ndarray
    seasonality: np.ndarray
    rep_calls: np.ndarray
    emails: np.ndarray
    samples: np.ndarray
    other_exposures: np.ndarray
    market_factors: pd.DataFrame
    marketing_activity: pd.DataFrame


def build_context(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    universe: HcpUniverse,
    generator: np.random.Generator,
) -> MarketContext:
    """Draw market indices and marketing activity for the whole window."""
    params = profile.context
    n_months = profile.months_of_history
    regions = taxonomies.region_codes
    n_regions = len(regions)
    brand_ids = tuple(taxonomies.brands["brand_id"].tolist())
    n_brands = len(brand_ids)
    brand_ordinal = {bid: i for i, bid in enumerate(brand_ids)}

    # --- market indices per (brand, region) --------------------------------
    n_cells = n_brands * n_regions
    access_mean = params.access_mean + generator.normal(0.0, params.access_cell_sd, n_cells)
    competitor_mean = params.competitor_mean + generator.normal(
        0.0, params.competitor_cell_sd, n_cells
    )
    access = _ar1_walk(
        generator,
        n_cells,
        n_months,
        access_mean,
        params.access_rho,
        params.access_innovation_sd,
        params.access_min,
        params.access_max,
    ).reshape(n_brands, n_regions, n_months)
    competitor = _ar1_walk(
        generator,
        n_cells,
        n_months,
        competitor_mean,
        params.competitor_rho,
        params.competitor_innovation_sd,
        params.competitor_min,
        params.competitor_max,
        drift_per_month=params.competitor_drift_per_year / 12.0,
    ).reshape(n_brands, n_regions, n_months)

    seasonality = seasonality_curve(profile, n_months)

    # --- marketing activity per (HCP, month) -------------------------------
    n_hcps = len(universe)
    z_opportunity = _zscore(universe.log_opportunity)[:, None]
    segment_rank = _segment_rank(universe, profile)[:, None]
    calendar = (profile.panel_start_month.month - 1 + np.arange(n_months)) % 12
    field_season = 1.0 + params.rep_calls_seasonality_amp * np.sin(2.0 * np.pi * calendar / 12.0)

    rep_log_mean = (
        params.rep_calls_log_intercept
        + params.rep_calls_opportunity_loading * z_opportunity
        + params.rep_calls_segment_step * segment_rank
        + np.log(field_season)[None, :]
    )
    rep_calls = generator.poisson(np.exp(rep_log_mean), size=(n_hcps, n_months))
    emails = generator.poisson(
        np.exp(params.emails_log_intercept + params.emails_opportunity_loading * z_opportunity),
        size=(n_hcps, n_months),
    )
    samples = generator.poisson(
        np.exp(params.samples_log_intercept + params.samples_opportunity_loading * z_opportunity),
        size=(n_hcps, n_months),
    )
    other_exposures = generator.poisson(
        np.exp(
            params.other_exposures_log_intercept
            + params.other_exposures_opportunity_loading * z_opportunity
        ),
        size=(n_hcps, n_months),
    )

    market_factors = _market_factor_frame(
        profile, taxonomies, brand_ids, regions, access, competitor, seasonality
    )
    marketing_activity = _marketing_frame(
        profile, universe, rep_calls, emails, samples, other_exposures
    )

    return MarketContext(
        brand_ids=brand_ids,
        brand_ordinal=brand_ordinal,
        access=access,
        competitor=competitor,
        seasonality=seasonality,
        rep_calls=rep_calls,
        emails=emails,
        samples=samples,
        other_exposures=other_exposures,
        market_factors=market_factors,
        marketing_activity=marketing_activity,
    )


def apply_program_halo(
    profile: SyntheticProfile,
    universe: HcpUniverse,
    context: MarketContext,
    invited_hcp_row: np.ndarray,
    invited_event_month: np.ndarray,
    generator: np.random.Generator,
) -> MarketContext:
    """Raise field activity in the months around every program an HCP was invited to.

    Returns a new :class:`MarketContext`; the arrays are rebuilt rather than
    mutated so that a caller holding the pre-halo context still sees pre-halo
    numbers.

    The uplift is a *fraction of that HCP's own baseline rate*, so a
    high-opportunity prescriber who already gets four calls a month gains more
    calls in absolute terms than a tail prescriber who gets one. That is both how
    field capacity is actually allocated and what keeps the halo from
    accidentally compressing the rep-call distribution.

    Two invited programs whose windows overlap accumulate, capped at
    ``1 + 2 * uplift``: a prescriber in the middle of a heavy quarter does get
    more attention, but not without limit.

    See ``ContextParams.halo_*`` for why this exists and why it deliberately
    attaches to the invitation rather than to attendance.
    """
    params = profile.context
    n_hcps, n_months = context.rep_calls.shape
    before, after = params.halo_months_before, params.halo_months_after

    # Triangular weight over [-before, +after], peaking at the event month, so the
    # activity ramps and decays instead of switching on and off.
    offsets = np.arange(-before, after + 1)
    span = np.where(
        offsets <= 0, (offsets + before + 1) / (before + 1), 1.0 - offsets / (after + 1)
    )

    intensity = np.zeros((n_hcps, n_months), dtype=np.float64)
    for offset, weight in zip(offsets, span, strict=True):
        month = invited_event_month + offset
        inside = (month >= 0) & (month < n_months)
        np.add.at(intensity, (invited_hcp_row[inside], month[inside]), weight)
    np.clip(intensity, 0.0, 2.0, out=intensity)

    def lift(counts: np.ndarray, uplift: float) -> np.ndarray:
        """Extra Poisson activity proportional to the existing rate."""
        if uplift <= 0.0:
            return counts
        # `counts` is itself a draw, so its own noise would be amplified by using
        # it as the rate. The HCP's mean over the window is the stable estimate of
        # the baseline rate and is what the uplift is defined against.
        baseline = counts.mean(axis=1, keepdims=True)
        return counts + generator.poisson(uplift * intensity * baseline)

    rep_calls = lift(context.rep_calls, params.halo_rep_call_uplift)
    emails = lift(context.emails, params.halo_email_uplift)
    samples = lift(context.samples, params.halo_sample_uplift)

    return replace(
        context,
        rep_calls=rep_calls,
        emails=emails,
        samples=samples,
        marketing_activity=_marketing_frame(
            profile, universe, rep_calls, emails, samples, context.other_exposures
        ),
    )


def _zscore(values: np.ndarray) -> np.ndarray:
    """Standardise, tolerating a degenerate (zero-variance) input."""
    sd = float(np.std(values))
    if sd < 1e-12:
        return np.zeros_like(values)
    return (values - float(np.mean(values))) / sd


def _segment_rank(universe: HcpUniverse, profile: SyntheticProfile) -> np.ndarray:
    """Segment as an ordinal 0..3, TIER_4 lowest. Used as a rep-effort driver."""
    order = {label: i for i, label in enumerate(profile.population.segment_labels)}
    return np.array([order[s] for s in universe.frame["segment_code"].to_numpy()], dtype=np.float64)


def _market_factor_frame(
    profile: SyntheticProfile,
    taxonomies: Taxonomies,
    brand_ids: tuple[str, ...],
    regions: tuple[str, ...],
    access: np.ndarray,
    competitor: np.ndarray,
    seasonality: np.ndarray,
) -> pd.DataFrame:
    """Long-form market factors, one row per (brand, region, month)."""
    n_months = profile.months_of_history
    brand_tenant = dict(
        zip(taxonomies.brands["brand_id"], taxonomies.brands["tenant_id"], strict=True)
    )
    b_idx, r_idx, m_idx = np.meshgrid(
        np.arange(len(brand_ids)), np.arange(len(regions)), np.arange(n_months), indexing="ij"
    )
    b_flat, r_flat, m_flat = b_idx.ravel(), r_idx.ravel(), m_idx.ravel()
    brand_col = np.asarray(brand_ids, dtype=object)[b_flat]
    return pd.DataFrame(
        {
            "tenant_id": [brand_tenant[b] for b in brand_col],
            "brand_id": brand_col,
            "region_code": np.asarray(regions, dtype=object)[r_flat],
            "month": month_index_to_date(profile, m_flat),
            "access_index": np.round(access[b_flat, r_flat, m_flat], 6),
            "competitor_index": np.round(competitor[b_flat, r_flat, m_flat], 6),
            "seasonality_index": np.round(seasonality[m_flat], 6),
        }
    )


def _marketing_frame(
    profile: SyntheticProfile,
    universe: HcpUniverse,
    rep_calls: np.ndarray,
    emails: np.ndarray,
    samples: np.ndarray,
    other_exposures: np.ndarray,
) -> pd.DataFrame:
    """Long-form marketing activity, one row per (HCP, month)."""
    n_hcps, n_months = rep_calls.shape
    hcp_ids = np.repeat(universe.frame["hcp_id"].to_numpy(), n_months)
    tenant_ids = np.repeat(universe.tenant_id, n_months)
    months = np.tile(np.arange(n_months), n_hcps)
    return pd.DataFrame(
        {
            "tenant_id": tenant_ids,
            "hcp_id": hcp_ids,
            "month": month_index_to_date(profile, months),
            "rep_calls": rep_calls.ravel().astype(np.int32),
            "emails_delivered": emails.ravel().astype(np.int32),
            "samples_dropped": samples.ravel().astype(np.int32),
            "other_promotional_exposures": other_exposures.ravel().astype(np.int32),
        }
    )
