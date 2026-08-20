"""M2 - the causal estimator: cohort-time ATT, event study, and a TWFE cross-check.

This is the module that produces the number the whole product is about, so the
design choices are stated before the code.

The estimand is multiplicative, not additive
--------------------------------------------
plan.md describes differencing NRx between arms. That cannot work here, and the
reason is structural rather than a matter of taste.

Prescribing responds proportionally: a program that lifts a prescriber's volume by
6% moves a 150-script writer by 9 scripts and a 15-script writer by 1. Attendees
are also selected to a higher level - by design, the standardised difference on
baseline volume before matching is 0.5-0.8. Put those two facts together and a
*level* difference-in-differences is biased even when nothing is wrong: any
market-wide movement common to both arms scales with each unit's own level, so it
produces a larger absolute change for the higher-level arm, and the estimator reads
that as an effect. A multiplicative outcome, selection on level, and additive
parallel trends cannot all hold; the first two are the realistic ones, so additive
parallel trends is what has to go.

So the identifying assumption is **parallel trends in ratios**: absent the program,
both arms' expected volume would have moved by the same *factor*. That is what the
synthetic generator satisfies (its outcome is ``exp(linear predictor)``) and what
the pre-trend diagnostic measures, in logs, at 0.001-0.019 log points.

Poisson pseudo-likelihood, not a regression on ``log(1+y)``
-----------------------------------------------------------
The obvious way to get a multiplicative estimand is to difference ``log(1+y)``.
That is the wrong tool and the reason is not obvious, which is why it is written
down. Monthly NRx contains genuine zeros, so the ``+1`` is doing real work - and the
ATT on ``log(1+y)`` depends on the units ``y`` is measured in. Rescale scripts to
scripts-per-thousand and the estimate changes, which means it is not a percentage
effect and cannot be reported as one (Chen and Roth, 2024).

Poisson pseudo-maximum-likelihood has none of that trouble. It models
``E[y] = exp(...)`` directly, so zeros are ordinary observations rather than a
problem to be patched, and the coefficient is a true log-ratio that is invariant to
the scale of ``y``. It does not assume the outcome is Poisson-distributed - the
estimator is consistent for the conditional mean under any distribution, which is
why it is standard for multiplicative models on non-count data. Overdispersion, which
monthly prescribing certainly has, affects only the standard errors, and those come
from a cluster bootstrap rather than from the likelihood.

The baseline enters as an offset: ``log(pre_mean)``. That is what makes the
specification a difference-in-differences rather than a cross-sectional comparison -
each unit is measured against its own pre-period level, so a unit fixed effect is
absorbed exactly instead of being estimated as one of several thousand parameters.

Cohort-time, then aggregate - never one pooled dummy
----------------------------------------------------
Events happen in different months, so treatment timing varies, and a single
two-way-fixed-effects dummy over staggered timing is a weighted average of
comparisons whose weights can be *negative* - including comparisons that use
already-treated units as controls (Goodman-Bacon, 2021). An estimate can then have
the wrong sign from correct data.

The primary estimator therefore follows Callaway and Sant'Anna's structure:
estimate an ATT separately within each event-month cohort, where every comparison is
treated-versus-not-yet-or-never-treated by construction, then aggregate those with
explicitly non-negative weights proportional to treated volume. TWFE is still
computed, and reported, purely as a divergence diagnostic: when it disagrees sharply
with the primary estimate that is information about the panel's timing structure, and
:attr:`~speaker_roi_core.enums.SensitivityTest.TWFE_CROSSCHECK` surfaces it.

Covariate adjustment discharges what matching left behind
---------------------------------------------------------
:attr:`~.matching.MatchResult.adjustment_covariates` is a contract, not a
suggestion. Matching fixes the large imbalances and deliberately leaves small ones -
see :func:`~.matching.balance_table` for why tightening the calipers to chase them
makes things worse - and the balance gate passes those covariates at a wider bound
*on the understanding that this module removes their residual bias by including them
in the outcome model*. So the covariates are included, and
:attr:`EstimatorResult.adjusted_for` records which, so a result can be checked
against the balance table that licensed it.

Reported in scripts, identified in ratios
-----------------------------------------
A finance team cannot act on "a 6.2% lift". The conversion is explicit and one-way:
the counterfactual post-period level for each treated unit is its own pre-period
level moved by the *control* arm's observed factor, and the incremental scripts are
that counterfactual multiplied by ``exp(att) - 1``. Every step of that is a quantity
this module estimated; nothing is imported from a plan assumption. It also makes
visible what the multiplicative model implies and the additive one hides - the same
percentage lift on a high-volume attendee is worth more scripts, which is why
attendee selection has value independent of the lift itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd
import structlog

from speaker_roi_core.enums import EstimatorKind

from .matching import MatchResult
from .panel import Cohort
from .spec import EstimatorSpec

__all__ = [
    "EstimatorResult",
    "estimate_att",
]

_LOG = structlog.get_logger(__name__)

#: Minimum observations per estimated parameter before a cohort is adjusted for
#: covariates rather than estimated as a plain ratio-of-ratios. Ten is the ordinary
#: rule of thumb; below it the adjustment fits noise and the cohort estimate becomes
#: less reliable than the unadjusted one it replaced.
MIN_ROWS_PER_PARAM: Final[int] = 10

#: Floor on a unit's pre-period level for it to enter the multiplicative estimator.
#: A unit with a zero baseline has no ratio to move: ``exp(att)`` applied to zero is
#: zero, and it contributes nothing to the estimate while still consuming a matched
#: slot. It is reported in ``n_zero_baseline`` rather than dropped silently, because
#: a cohort that is mostly zero-baseline is a coverage finding.
MIN_BASELINE: Final[float] = 1e-9

#: Offset used as the event study's reference period. Callaway and Sant'Anna's
#: convention: the month before exposure. The primary estimate uses the full
#: pre-window mean instead, because it is far more precise - the two baselines serve
#: different purposes and using the precise one for the pre-trend test would be
#: circular, since the pre-period observations would appear on both sides.
EVENT_STUDY_REFERENCE: Final[int] = -1


@dataclass(frozen=True, slots=True)
class EstimatorResult:
    """A causal estimate with everything needed to judge it.

    Nothing here is optional decoration. ``att_log`` without ``pre_trend_gap`` is an
    assertion; ``incremental_total`` without ``ci_low``/``ci_high`` invites a
    point-estimate decision on an interval that may include zero. The evidence layer
    reads all of it.
    """

    #: The primary estimate: aggregated cohort-time ATT on the log scale, so a value
    #: of 0.06 means attendance multiplied post-period volume by ``exp(0.06)``.
    att_log: float
    #: Cluster-bootstrap percentile interval on ``att_log``.
    ci_low: float
    ci_high: float
    #: Cluster-bootstrap standard deviation of ``att_log``. Reported alongside the
    #: percentile interval, not used to build it: the bootstrap distribution of a
    #: log-ratio is asymmetric, and a symmetric interval would misstate both ends.
    se: float

    #: Incremental scripts per matched attendee over the whole post window, and the
    #: cohort total. See the module docstring for the conversion.
    incremental_per_attendee: float
    incremental_total: float
    incremental_ci_low: float
    incremental_ci_high: float

    #: One row per (cohort month, post offset) with its own ATT. The decomposition
    #: the Method panel shows, and the input to ``LEAVE_ONE_MONTH_OUT``.
    cohort_time: pd.DataFrame
    #: ATT by month offset relative to :data:`EVENT_STUDY_REFERENCE`. Pre-period rows
    #: are the parallel-trends evidence; post-period rows show the effect profile.
    event_study: pd.DataFrame

    #: Difference between arms in log growth across the baseline window. The quantity
    #: :attr:`~.spec.GateThresholds.max_pre_trend_gap` gates; see
    #: :func:`_pre_trend_gap` for why it is this statistic and not the one below.
    pre_trend_gap: float
    #: The same statistic on the weights *matching* produced, before entropy balancing
    #: was allowed to target the trend directly (:data:`~.matching.TREND_COVARIATES`).
    #: This is the number the gate reads, and the distinction is not pedantic: a moment
    #: the solver was instructed to satisfy is satisfied whatever the design does, so
    #: gating on the refined figure would be gating on the constraint rather than on
    #: the data. The refined weights produce the estimate because parallel trends is
    #: better satisfied than violated; the unrefined weights decide whether to believe
    #: it. Equal to :attr:`pre_trend_gap` when the refinement was refused.
    pre_trend_gap_unrefined: float
    #: Largest absolute pre-period *event-study* coefficient. Displayed beside the
    #: event study so a reader can see how much of its shape is noise; deliberately
    #: not gated, because a single-month contrast against a single reference month is
    #: several times noisier than the statistic the threshold was calibrated on.
    worst_pre_month: float

    #: Two-way fixed effects on the same panel, and its absolute divergence from the
    #: primary estimate. A diagnostic; see the module docstring.
    twfe_att_log: float
    twfe_divergence: float

    n_treated: int
    n_controls: int
    n_cohorts: int
    n_cohorts_estimated: int
    n_zero_baseline: int
    n_bootstrap: int
    #: Covariates actually included in the outcome model, honouring
    #: :attr:`~.matching.MatchResult.adjustment_covariates`. Empty when every cohort
    #: was too small to adjust - which is itself a warning, recorded below.
    adjusted_for: tuple[str, ...]
    estimator: EstimatorKind
    spec: EstimatorSpec
    #: False when the cohort could not support an estimate at all. The evidence layer
    #: turns this into NOT_ESTIMABLE; it is never a zero effect.
    estimable: bool = True
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def att_ratio(self) -> float:
        """Multiplicative effect: 1.062 means a 6.2% lift."""
        return float(np.exp(self.att_log))

    @property
    def att_lift_pct(self) -> float:
        return float((np.exp(self.att_log) - 1.0) * 100.0)

    @property
    def crosses_zero(self) -> bool:
        """Whether the interval admits no effect.

        Read by the evidence layer and by the UI, which must not present a
        directional claim from an interval spanning zero however large the point
        estimate is.
        """
        return not (self.ci_low > 0.0 or self.ci_high < 0.0)


def _ppml(
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    offset: np.ndarray,
    *,
    max_iter: int = 60,
    tol: float = 1e-9,
) -> tuple[np.ndarray, bool]:
    """Weighted Poisson pseudo-ML by iteratively reweighted least squares.

    Written out rather than delegated because it sits inside the bootstrap loop and
    runs some thousands of times per estimate, and because the failure behaviour has
    to be explicit: a bootstrap replicate that does not converge must be *dropped*,
    not silently returned as whatever the last iterate happened to be. Returns the
    coefficients and whether it converged.

    The tiny ridge on the normal equations is numerical, not statistical - adjustment
    covariates are correlated by construction (volume, TRx and decile all measure
    prescriber size), and a bootstrap resample can make the cross-product singular.
    At 1e-10 relative to the diagonal it cannot move a coefficient that is
    identified, and it stops a resample from taking the whole estimate down.
    """
    beta = np.zeros(x.shape[1], dtype=float)
    positive = y > 0
    if positive.any():
        # Start at the intercept implied by the offset, which is close enough that
        # IRLS converges in a handful of steps rather than wandering.
        beta[0] = float(np.log(y[positive].mean()) - offset[positive].mean())

    for _ in range(max_iter):
        eta = x @ beta + offset
        # Clipping bounds mu to (1e-13, 1e13). Unbounded eta in an early iterate
        # overflows exp and poisons the whole fit with nan.
        mu = np.exp(np.clip(eta, -30.0, 30.0))
        working_w = w * mu
        z = (x @ beta) + (y - mu) / mu
        xtw = x * working_w[:, None]
        lhs = x.T @ xtw
        lhs.flat[:: lhs.shape[0] + 1] += 1e-10 * np.trace(lhs) / max(lhs.shape[0], 1)
        try:
            new = np.linalg.solve(lhs, xtw.T @ z)
        except np.linalg.LinAlgError:
            return beta, False
        if not np.all(np.isfinite(new)):
            return beta, False
        step = float(np.max(np.abs(new - beta)))
        beta = new
        if step < tol:
            return beta, True
    return beta, False


def _design(frame: pd.DataFrame, covariates: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    """Design matrix ``[1, treated, standardised covariates]`` and the offset.

    Covariates are standardised so the ridge in :func:`_ppml` and the convergence
    tolerance mean the same thing whether a column is a decile from 1 to 10 or a
    share from 0 to 1. It does not change the treated coefficient, which is the only
    one anybody reads.

    Missing covariate values are set to the column mean *after* standardising, i.e.
    to zero. Unlike the propensity model - where missingness is informative and
    LightGBM learns a direction for it - here the covariate is a nuisance term whose
    only job is to soak up residual imbalance, and dropping the row instead would
    discard a matched unit for the sake of a control variable.
    """
    treated = frame["is_treated"].to_numpy(dtype=float)
    columns = [np.ones(len(frame)), treated]
    for name in covariates:
        values = frame[name].to_numpy(dtype=float)
        centre = np.nanmean(values) if np.isfinite(values).any() else 0.0
        scale = np.nanstd(values)
        scaled = (values - centre) / (scale if scale > 0 else 1.0)
        columns.append(np.nan_to_num(scaled, nan=0.0))
    offset = np.log(frame["_baseline"].to_numpy(dtype=float))
    return np.column_stack(columns), offset


def _cohort_att(
    frame: pd.DataFrame, covariates: tuple[str, ...]
) -> tuple[float, bool, tuple[str, ...]]:
    """ATT within one event-month cohort, adjusted where the cohort can carry it.

    Returns the log-ratio, whether it is usable, and the covariates that were
    actually used - which may be fewer than requested, because a covariate that is
    constant inside this cohort carries no information and would only make the
    cross-product singular.
    """
    if frame["is_treated"].nunique() < 2:
        return float("nan"), False, ()

    usable = tuple(
        name
        for name in covariates
        if name in frame and float(np.nanstd(frame[name].to_numpy(dtype=float))) > 0
    )
    # Two parameters (intercept, treatment) plus one per covariate. Adjustment is
    # dropped wholesale rather than trimmed to fit: a cohort that can afford three of
    # nine covariates is adjusting for an arbitrary subset, which is harder to
    # interpret than not adjusting at all.
    if len(frame) < MIN_ROWS_PER_PARAM * (len(usable) + 2):
        usable = ()

    x, offset = _design(frame, usable)
    beta, ok = _ppml(
        x, frame["_post"].to_numpy(dtype=float), frame["_w"].to_numpy(dtype=float), offset
    )
    return (float(beta[1]) if ok else float("nan")), ok, usable


def _aggregate(prepared: pd.DataFrame, covariates: tuple[str, ...]) -> tuple[float, dict]:
    """Cohort-time ATTs aggregated by treated weight.

    The weights are the treated arm's own weight share per cohort, so the aggregate
    answers "what was the effect on the attendees who actually attended" rather than
    giving a 12-attendee event the same say as a 200-attendee one. They are
    non-negative by construction, which is the property TWFE cannot promise.
    """
    parts: list[tuple[float, float]] = []
    used: set[str] = set()
    estimated = 0
    for _, block in prepared.groupby("_cohort", sort=True):
        att, ok, cols = _cohort_att(block, covariates)
        if not ok or not np.isfinite(att):
            continue
        weight = float(block.loc[block["is_treated"], "_w"].sum())
        if weight <= 0:
            continue
        parts.append((att, weight))
        used.update(cols)
        estimated += 1
    if not parts:
        return float("nan"), {"n_cohorts_estimated": 0, "adjusted_for": ()}
    values = np.array([p[0] for p in parts])
    weights = np.array([p[1] for p in parts])
    pooled = float((values * weights).sum() / weights.sum())
    return pooled, {
        "n_cohorts_estimated": estimated,
        "adjusted_for": tuple(c for c in covariates if c in used),
    }


def _cohort_time_grid(prepared: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    """ATT for each (cohort month, post offset), unadjusted.

    Deliberately the plain weighted ratio-of-ratios rather than a per-cell PPML: a
    single cohort-offset cell can hold a few dozen units, which will not support nine
    nuisance parameters. The grid's job is to show *where* the effect came from and to
    feed the leave-one-month-out sensitivity test, and for both of those the
    unadjusted cell estimate is the more stable choice. The adjusted number is the
    aggregate, which is what gets reported.
    """
    joined = monthly.merge(
        prepared[["event_id", "hcp_id", "_cohort", "_w", "_baseline", "is_treated"]],
        on=["event_id", "hcp_id"],
        how="inner",
        suffixes=("", "_p"),
    )
    post = joined[joined["offset"] > 0]
    rows: list[dict[str, object]] = []
    for (cohort, offset), block in post.groupby(["_cohort", "offset"], sort=True):
        ratios = {}
        for arm in (True, False):
            side = block[block["is_treated"] == arm]
            base = float((side["_baseline"] * side["_w"]).sum())
            level = float((side["outcome"] * side["_w"]).sum())
            ratios[arm] = level / base if base > MIN_BASELINE else np.nan
        att = (
            float(np.log(ratios[True] / ratios[False]))
            if ratios[True] and ratios[False] and np.isfinite([ratios[True], ratios[False]]).all()
            else float("nan")
        )
        treated_side = block[block["is_treated"]]
        rows.append(
            {
                "cohort_month": int(cohort),
                "offset": int(offset),
                "att_log": att,
                "att_lift_pct": float((np.exp(att) - 1) * 100) if np.isfinite(att) else np.nan,
                "n_treated": int(treated_side["hcp_id"].nunique()),
                "treated_weight": float(treated_side["_w"].sum()),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "cohort_month",
            "offset",
            "att_log",
            "att_lift_pct",
            "n_treated",
            "treated_weight",
        ],
    )


def _event_study(
    prepared: pd.DataFrame, monthly: pd.DataFrame, spec: EstimatorSpec
) -> pd.DataFrame:
    """ATT by month offset, normalised to the month before exposure.

    Each arm's volume at offset ``t`` is divided by its own volume at the reference
    month, and the two are divided by each other. Pre-period rows should be flat
    around zero: they are periods in which nothing had happened yet, so anything else
    is either a violation of parallel trends or anticipation, and both invalidate the
    design.

    A unit missing the reference month is dropped from this table only - it still
    contributes to the primary estimate, which uses the full-window baseline and does
    not depend on any single month being observed.
    """
    joined = monthly.merge(
        prepared[["event_id", "hcp_id", "_w", "is_treated"]],
        on=["event_id", "hcp_id"],
        how="inner",
        suffixes=("", "_p"),
    )
    reference = joined[joined["offset"] == EVENT_STUDY_REFERENCE]
    base = {}
    for arm in (True, False):
        side = reference[reference["is_treated"] == arm]
        base[arm] = float((side["outcome"] * side["_w"]).sum())
    if min(base.values()) <= MIN_BASELINE:
        return pd.DataFrame(columns=["offset", "att_log", "n_treated", "is_pre"])

    rows: list[dict[str, object]] = []
    offsets = [*range(-spec.pre_window_months, 0), *range(1, spec.post_window_months + 1)]
    for offset in offsets:
        block = joined[joined["offset"] == offset]
        if block.empty:
            continue
        ratios = {}
        for arm in (True, False):
            side = block[block["is_treated"] == arm]
            ratios[arm] = float((side["outcome"] * side["_w"]).sum()) / base[arm]
        att = (
            float(np.log(ratios[True] / ratios[False]))
            if ratios[True] > 0 and ratios[False] > 0
            else float("nan")
        )
        rows.append(
            {
                "offset": offset,
                "att_log": 0.0 if offset == EVENT_STUDY_REFERENCE else att,
                "att_lift_pct": 0.0
                if offset == EVENT_STUDY_REFERENCE
                else (float((np.exp(att) - 1) * 100) if np.isfinite(att) else np.nan),
                "n_treated": int(block.loc[block["is_treated"], "hcp_id"].nunique()),
                "is_pre": offset < 0,
                "is_reference": offset == EVENT_STUDY_REFERENCE,
            }
        )
    return pd.DataFrame(rows)


def _rebase(prepared: pd.DataFrame, matches: MatchResult) -> pd.DataFrame:
    """``prepared`` with the pre-refinement matching weights substituted back in.

    Used only for diagnostics the refinement is allowed to target, so that the
    diagnostic still measures the design rather than the constraint. Cheap enough to
    run unconditionally: when the refinement was refused the two weight sets are the
    same object and the result is identical by construction.
    """
    lookup = matches.base_weights.set_index(["event_id", "hcp_id"])["weight"]
    out = prepared.copy()
    keys = pd.MultiIndex.from_frame(out[["event_id", "hcp_id"]])
    out["_w"] = keys.map(lookup).to_numpy(dtype=float)
    return out


def _pre_trend_gap(prepared: pd.DataFrame, monthly: pd.DataFrame, spec: EstimatorSpec) -> float:
    """Difference between arms in log growth across the pre window, weighted by event.

    This, and not the event study, is what the parallel-trends gate reads. The two
    measure the same thing at very different precision, and the gate threshold was
    calibrated against this one.

    The statistic is a half-window contrast: mean log volume over the second half of
    the baseline window minus the first half, differenced between arms, averaged
    across events weighted by treated volume. Every one of the six pre-period months
    contributes, so its sampling noise stays small on the synthetic panel, where
    parallel trends genuinely holds: 0.001 to 0.019 log points over the full invited
    cohort, and 0.0142 to 0.0304 over the *matched* cohort across five seeds. The
    matched figure is the larger of the two and the one this function returns - matching
    discards roughly a fifth of the units, so the same zero is estimated less precisely
    - which is why :attr:`~.spec.GateThresholds.max_pre_trend_gap` at 0.05 is set
    against that noisier number and still clears it by a factor of 1.6. It is the same
    statistic
    ``scripts/devtools/dgp_diagnostics.py`` uses to assert the generator satisfies
    parallel trends, so the gate and the generator's own guarantee are measured on one
    scale rather than two.

    The event study instead contrasts each single month against the single month
    before exposure, which is the standard specification and the right one for *seeing*
    an effect profile - but one month of a few hundred prescribers' scripts against
    another single month carries several times this statistic's noise. Measured on the
    synthetic cohort its worst pre-period coefficient reaches 0.066 while this
    statistic reads 0.030 on the same five seeds - and on the seed where the event
    study peaks at 0.064, this statistic reads 0.024. Roughly half the event study's
    apparent pre-trend is the reference month, not a trend. Gating on the noisier of the two would fail correct cohorts, so the event
    study is displayed and this is gated.

    Logs, here as everywhere in this package, because the outcome is multiplicative -
    see the module docstring. ``log1p`` rather than ``log`` because a single month can
    legitimately be zero even for a unit whose window baseline is not.
    """
    half = spec.pre_window_months // 2
    if half < 1:
        return float("nan")
    joined = monthly.merge(
        prepared[["event_id", "hcp_id", "_w", "is_treated"]],
        on=["event_id", "hcp_id"],
        how="inner",
        suffixes=("", "_p"),
    )
    pre = joined[joined["offset"] < 0].copy()
    if pre.empty:
        return float("nan")
    pre["_log"] = np.log1p(pre["outcome"].to_numpy(dtype=float))
    pre["_late"] = pre["offset"] >= -half

    per_unit = (
        pre.groupby(["event_id", "hcp_id", "is_treated", "_w", "_late"], as_index=False)["_log"]
        .mean()
        .pivot_table(
            index=["event_id", "hcp_id", "is_treated", "_w"], columns="_late", values="_log"
        )
    )
    if True not in per_unit.columns or False not in per_unit.columns:
        return float("nan")
    steps = (per_unit[True] - per_unit[False]).dropna().rename("step").reset_index()
    if steps.empty:
        return float("nan")

    gaps: list[tuple[float, float]] = []
    for _, block in steps.groupby("event_id", sort=False):
        arms = {}
        for arm in (True, False):
            side = block[block["is_treated"] == arm]
            total = float(side["_w"].sum())
            if total <= 0:
                break
            arms[arm] = float((side["step"] * side["_w"]).sum() / total)
        if len(arms) < 2:
            continue
        gaps.append((arms[True] - arms[False], float(block.loc[block["is_treated"], "_w"].sum())))
    if not gaps:
        return float("nan")
    values = np.array([g[0] for g in gaps])
    weights = np.array([g[1] for g in gaps])
    return float(abs((values * weights).sum() / weights.sum()))


def _twfe(prepared: pd.DataFrame, monthly: pd.DataFrame) -> float:
    """Two-way fixed effects on ``log1p`` outcome - the diagnostic, not the estimate.

    Unit and period effects are removed by alternating projections, then a single
    ``treated x post`` dummy is regressed on the residual. This is deliberately the
    naive specification the literature warns about: staggered timing gives it
    possibly-negative implicit weights, and ``log1p`` makes its coefficient
    scale-dependent. Both defects are the point - it is here to disagree, and the size
    of the disagreement is the signal.
    """
    joined = monthly.merge(
        prepared[["event_id", "hcp_id", "_w", "is_treated"]],
        on=["event_id", "hcp_id"],
        how="inner",
        suffixes=("", "_p"),
    )
    if joined.empty:
        return float("nan")
    unit = joined["event_id"].astype(str) + "|" + joined["hcp_id"].astype(str)
    y = np.log1p(joined["outcome"].to_numpy(dtype=float))
    d = (joined["is_treated"].to_numpy(dtype=bool) & (joined["offset"].to_numpy() > 0)).astype(
        float
    )
    w = joined["_w"].to_numpy(dtype=float)
    frame = pd.DataFrame(
        {"unit": unit.to_numpy(), "period": joined["mi"].to_numpy(), "y": y, "d": d, "w": w}
    )

    for _ in range(30):
        before = frame[["y", "d"]].to_numpy().copy()
        for key in ("unit", "period"):
            grouped = frame.groupby(key, sort=False)
            for column in ("y", "d"):
                means = grouped.apply(
                    lambda g, c=column: (
                        np.average(g[c], weights=g["w"]) if g["w"].sum() > 0 else 0.0
                    ),
                    include_groups=False,
                )
                frame[column] = frame[column] - frame[key].map(means).to_numpy()
        if np.max(np.abs(frame[["y", "d"]].to_numpy() - before)) < 1e-8:
            break

    dd = frame["d"].to_numpy()
    denominator = float((frame["w"] * dd * dd).sum())
    if denominator <= 1e-12:
        return float("nan")
    return float((frame["w"] * dd * frame["y"]).sum() / denominator)


def _prepare(cohort: Cohort, matches: MatchResult, features: pd.DataFrame) -> pd.DataFrame:
    """Matched units with their weight, baseline, post level and cohort month.

    One row per analysed unit. The join is on the matched weights, so a unit that
    found no match is absent here by construction rather than by a filter that could
    be forgotten - which is the same reason the propensity stage hands its support
    decision forward instead of letting each stage re-derive it.
    """
    keys = ["event_id", "hcp_id"]
    frame = matches.weights.merge(
        cohort.units[
            [*keys, "tenant_id", "brand_id", "event_month_index", "pre_mean", "post_mean"]
        ],
        on=keys,
        how="inner",
    )
    frame = frame.merge(features.drop(columns=["tenant_id", "brand_id"]), on=keys, how="left")
    frame = frame.rename(columns={"weight": "_w"})
    frame["_cohort"] = frame["event_month_index"].astype(int)
    frame["_baseline"] = frame["pre_mean"].astype(float)
    frame["_post"] = frame["post_mean"].astype(float)
    return frame


def estimate_att(
    cohort: Cohort,
    matches: MatchResult,
    features: pd.DataFrame,
    spec: EstimatorSpec,
) -> EstimatorResult:
    """Estimate the ATT of attendance on post-period brand prescribing.

    Returns a result with ``estimable=False`` rather than raising when the cohort
    cannot support an estimate. A refusal that carries its diagnostics can be
    explained to the person who asked; an exception cannot, and the product's whole
    posture is that "we cannot tell you" is a legitimate answer that has to be
    *displayable*.
    """
    warnings: list[str] = []
    prepared = _prepare(cohort, matches, features)
    n_all = len(prepared)
    prepared = prepared[np.isfinite(prepared["_baseline"]) & np.isfinite(prepared["_post"])]
    zero_baseline = int((prepared["_baseline"] <= MIN_BASELINE).sum())
    prepared = prepared[prepared["_baseline"] > MIN_BASELINE].reset_index(drop=True)
    if zero_baseline:
        warnings.append(
            f"{zero_baseline} of {n_all} matched units have a zero pre-period baseline "
            "and cannot contribute to a multiplicative estimate"
        )

    n_treated = int(prepared["is_treated"].sum())
    n_controls = int((~prepared["is_treated"]).sum())
    covariates = matches.adjustment_covariates
    monthly = cohort.monthly

    def refuse(reason: str) -> EstimatorResult:
        return EstimatorResult(
            att_log=float("nan"),
            ci_low=float("nan"),
            ci_high=float("nan"),
            se=float("nan"),
            incremental_per_attendee=float("nan"),
            incremental_total=float("nan"),
            incremental_ci_low=float("nan"),
            incremental_ci_high=float("nan"),
            cohort_time=pd.DataFrame(),
            event_study=pd.DataFrame(),
            pre_trend_gap=float("nan"),
            pre_trend_gap_unrefined=float("nan"),
            worst_pre_month=float("nan"),
            twfe_att_log=float("nan"),
            twfe_divergence=float("nan"),
            n_treated=n_treated,
            n_controls=n_controls,
            n_cohorts=int(prepared["_cohort"].nunique()) if len(prepared) else 0,
            n_cohorts_estimated=0,
            n_zero_baseline=zero_baseline,
            n_bootstrap=0,
            adjusted_for=(),
            estimator=spec.primary_estimator,
            spec=spec,
            estimable=False,
            warnings=(*warnings, reason),
        )

    if n_treated < spec.gates.min_treated or n_controls < spec.gates.min_controls:
        return refuse(
            f"cohort too small to estimate: {n_treated} treated (need "
            f"{spec.gates.min_treated}), {n_controls} controls (need {spec.gates.min_controls})"
        )

    att, meta = _aggregate(prepared, covariates)
    if not np.isfinite(att):
        return refuse("no event-month cohort produced a converged estimate")
    if not meta["adjusted_for"] and covariates:
        warnings.append(
            f"no cohort was large enough to adjust for {len(covariates)} residual-imbalance "
            "covariates; the estimate carries whatever bias they represent"
        )

    # --- cluster bootstrap ------------------------------------------------
    # Resampled by prescriber, not by row. A prescriber appears at several events and
    # a control serves several treated units, so rows are correlated in two ways;
    # resampling rows would treat that shared information as independent and produce
    # an interval that is too narrow. Prescriber is the coarsest of the two groupings
    # and therefore the conservative choice.
    clusters = prepared[spec.cluster_on].to_numpy()
    unique = np.unique(clusters)
    index_by_cluster = {c: np.flatnonzero(clusters == c) for c in unique}
    rng = np.random.default_rng(spec.bootstrap_seed)
    draws: list[float] = []
    for _ in range(spec.bootstrap_replications):
        picked = rng.choice(unique, size=unique.size, replace=True)
        rows = np.concatenate([index_by_cluster[c] for c in picked])
        replicate, _meta = _aggregate(prepared.iloc[rows], covariates)
        if np.isfinite(replicate):
            draws.append(replicate)
    if len(draws) < spec.bootstrap_replications // 2:
        warnings.append(
            f"only {len(draws)} of {spec.bootstrap_replications} bootstrap replicates "
            "converged; the interval is wider than reported"
        )
    if not draws:
        return refuse("bootstrap produced no usable replicates, so no interval can be given")

    alpha = (1.0 - spec.confidence_level) / 2.0
    ci_low, ci_high = (float(v) for v in np.quantile(draws, [alpha, 1.0 - alpha]))
    se = float(np.std(draws, ddof=1)) if len(draws) > 1 else float("nan")

    # --- level conversion --------------------------------------------------
    # The counterfactual is each treated unit's own baseline moved by the control
    # arm's observed factor. Using the control factor rather than 1.0 matters: brand
    # volume drifts for reasons that have nothing to do with the program, and
    # attributing that drift to attendance is the single most common way a lift number
    # gets overstated.
    treated_side = prepared[prepared["is_treated"]]
    control_side = prepared[~prepared["is_treated"]]
    control_base = float((control_side["_baseline"] * control_side["_w"]).sum())
    control_post = float((control_side["_post"] * control_side["_w"]).sum())
    control_factor = control_post / control_base if control_base > MIN_BASELINE else float("nan")
    counterfactual_monthly = (
        float((treated_side["_baseline"] * treated_side["_w"]).sum()) * control_factor
    )
    treated_weight = float(treated_side["_w"].sum())

    def to_scripts(log_effect: float) -> tuple[float, float]:
        """Per-attendee and total incremental scripts implied by a log effect."""
        if not np.isfinite(log_effect) or not np.isfinite(counterfactual_monthly):
            return float("nan"), float("nan")
        total = counterfactual_monthly * (np.exp(log_effect) - 1.0) * spec.post_window_months
        per = total / treated_weight if treated_weight > 0 else float("nan")
        return float(per), float(total)

    per_attendee, total = to_scripts(att)
    _, inc_low = to_scripts(ci_low)
    _, inc_high = to_scripts(ci_high)

    # --- diagnostics -------------------------------------------------------
    grid = _cohort_time_grid(prepared, monthly)
    study = _event_study(prepared, monthly, spec)
    pre_gap = _pre_trend_gap(prepared, monthly, spec)
    pre_gap_unrefined = _pre_trend_gap(_rebase(prepared, matches), monthly, spec)
    pre = study[study["is_pre"] & ~study["is_reference"]] if not study.empty else study
    worst_month = float(pre["att_log"].abs().max()) if not pre.empty else float("nan")
    twfe = _twfe(prepared, monthly)
    divergence = abs(twfe - att) if np.isfinite(twfe) else float("nan")

    if np.isfinite(pre_gap_unrefined) and pre_gap_unrefined > spec.gates.max_pre_trend_gap:
        warnings.append(
            f"pre-period trends diverge by {pre_gap_unrefined:.4f} log points before "
            f"balancing (gate allows {spec.gates.max_pre_trend_gap}); parallel trends "
            f"is doubtful"
        )

    result = EstimatorResult(
        att_log=att,
        ci_low=ci_low,
        ci_high=ci_high,
        se=se,
        incremental_per_attendee=per_attendee,
        incremental_total=total,
        incremental_ci_low=inc_low,
        incremental_ci_high=inc_high,
        cohort_time=grid,
        event_study=study,
        pre_trend_gap=pre_gap,
        pre_trend_gap_unrefined=pre_gap_unrefined,
        worst_pre_month=worst_month,
        twfe_att_log=twfe,
        twfe_divergence=divergence,
        n_treated=n_treated,
        n_controls=n_controls,
        n_cohorts=int(prepared["_cohort"].nunique()),
        n_cohorts_estimated=int(meta["n_cohorts_estimated"]),
        n_zero_baseline=zero_baseline,
        n_bootstrap=len(draws),
        adjusted_for=meta["adjusted_for"],
        estimator=spec.primary_estimator,
        spec=spec,
        warnings=tuple(warnings),
    )
    _LOG.info(
        "causal.estimator.done",
        spec=spec.fingerprint,
        att_log=att,
        lift_pct=result.att_lift_pct,
        ci=(ci_low, ci_high),
        crosses_zero=result.crosses_zero,
        incremental_total=total,
        treated=n_treated,
        controls=n_controls,
        cohorts=f"{meta['n_cohorts_estimated']}/{result.n_cohorts}",
        pre_trend_gap=pre_gap,
        pre_trend_gap_unrefined=pre_gap_unrefined,
        worst_pre_month=worst_month,
        twfe_divergence=divergence,
        bootstrap=len(draws),
        adjusted=len(meta["adjusted_for"]),
    )
    return result
