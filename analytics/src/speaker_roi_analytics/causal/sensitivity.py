"""Robustness battery: does the estimate survive being asked differently?

A single ATT with a bootstrap interval answers one question - how much would this
number move if we drew a different sample of the same prescribers? That is the *only*
uncertainty a confidence interval describes, and on observational program data it is
rarely the largest one. The larger question is whether the number moves when a
defensible analyst choice is made differently, and whether it could be produced by
something the design never observed.

This module answers both, and keeps them separate:

**Specification uncertainty** - eight variations, each re-running the pipeline with one
decision changed and nothing else. The caliper, the control ratio, the post window, the
eligibility rule. A result that halves when the caliper moves from 0.5 to 1.0 standard
deviations was a property of the caliper, and
:attr:`~.spec.GateThresholds.max_sensitivity_spread` fails it.

**Bias from what was never measured** - benchmarked against what *was* measured. Each
of the propensity model's most important covariates is removed in turn and the pipeline
re-run; the largest movement is how far a single confounder of a strength this data
demonstrably contains can push the answer. An unmeasured confounder at least that
strong is entirely plausible - prescriber ambition, a competitor's parallel campaign,
a therapy-area guideline change - so that movement becomes a bias bound, and the
reported interval is widened by it.

Why the widened interval is not a confidence interval
-----------------------------------------------------
:attr:`SensitivityReport.robust_ci_low` and ``robust_ci_high`` are a *partial
identification* range: the union of the sampling intervals across the bias bound, in
the sense of Imbens (2003) and Cinelli & Hazlett (2020). There is no 95% attached to
it, and pretending otherwise would be worse than not reporting it. What it supports is
exactly one claim, which happens to be the claim the product needs: whether the
conclusion's *sign* survives a confounder as strong as the ones we can see. When it
does not, the honest grade is :attr:`~speaker_roi_core.enums.EvidenceGrade.DIRECTIONAL`
or below however tight the bootstrap interval was, and :mod:`.evidence` enforces that.

Measured on synthetic data where the truth is known, the narrow bootstrap interval
already covers the truth on 5 of 5 seeds while a naive attendee pre/post comparison
overstates it by 5.1 to 8.1 times. The bias bound is not there to fix a broken
estimator; it is there because a *correct* estimator on this kind of data still cannot
rule out that it got lucky, and the interval a decision is made from should say so.

Cost
----
Each variation is a full pipeline run. They use a reduced bootstrap
(:data:`VARIANT_BOOTSTRAP`) because only the point estimate is read from them, which is
what keeps the whole suite to roughly three times the primary estimate's cost rather
than thirty.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd
import structlog

from speaker_roi_core.enums import SensitivityTest

from .estimator import EstimatorResult, estimate_att
from .features import PROPENSITY_COLUMNS, build_features
from .matching import match_cohort
from .panel import Cohort, PanelFrames, build_cohort
from .propensity import fit_propensity
from .spec import EstimatorSpec

__all__ = [
    "BENCHMARK_COVARIATES",
    "CONFOUNDER_STRENGTH",
    "VARIANT_BOOTSTRAP",
    "SensitivityReport",
    "SensitivityRun",
    "run_sensitivity",
]

_LOG = structlog.get_logger(__name__)

#: Bootstrap replicates for a variation, against the primary's 400. Variations
#: contribute their point estimate to the spread and nothing else, so the interval
#: around them is never read; this is enough to keep the estimator's "did the bootstrap
#: converge" path meaningful without paying for precision no one uses.
VARIANT_BOOTSTRAP = 60

#: How many observed covariates to benchmark the unmeasured-confounder bound against,
#: taken in the propensity model's own importance order. Every covariate would be more
#: thorough and roughly doubles the suite's cost; the bound is a maximum over the set,
#: and importance rank is a good predictor of which one moves the estimate, so the tail
#: contributes little. Recorded in the report so a reader knows the bound was taken over
#: three and not over everything.
BENCHMARK_COVARIATES = 3

#: Multiple of the strongest observed covariate's influence that the bound assumes an
#: unmeasured confounder could reach. 1.0 says "as strong as the strongest thing we
#: measured". Raising it is a policy decision about how adversarial the reader wants to
#: be, not a statistical one, which is why it is a named constant rather than a fitted
#: quantity: the data cannot inform it. See the module docstring on why the resulting
#: range is not a confidence interval.
CONFOUNDER_STRENGTH = 1.0

#: Below this the primary estimate is indistinguishable from zero on the log scale, and
#: every ratio-to-primary in this module would divide by noise. Tests then report
#: ``applicable=False`` rather than a number: "the placebo found 30 times the real
#: effect" is meaningless when the real effect is 0.0001.
_MIN_PRIMARY_ATT = 0.005


@dataclass(frozen=True, slots=True)
class SensitivityRun:
    """One variation and what it produced."""

    test: SensitivityTest
    #: What was changed, in words, for the Method panel. Not the enum name: several
    #: runs share a test member and only this distinguishes them.
    label: str
    att_log: float
    incremental_total: float
    #: ``|att - primary| / |primary|``. NaN when the primary is too near zero to
    #: divide by; see :data:`_MIN_PRIMARY_ATT`.
    deviation: float
    #: False when the variation could not be estimated at all - too few units survived
    #: the changed rule, usually. Distinguished from a large deviation because they
    #: mean different things: one is missing evidence, the other is bad news.
    estimable: bool
    #: Whether the deviation is meaningful enough to count toward the spread.
    applicable: bool
    note: str = ""


@dataclass(frozen=True, slots=True)
class SensitivityReport:
    """The battery's verdict, and the interval a decision should actually be made from."""

    runs: tuple[SensitivityRun, ...]

    #: Largest applicable :attr:`SensitivityRun.deviation` over the specification
    #: variations, excluding the placebo and the confounder benchmark - those are
    #: separate questions with separate gates, and folding them in here would let a
    #: correctly-failing placebo masquerade as instability.
    spread: float
    #: Placebo ATT as a share of the primary. Gated by
    #: :attr:`~.spec.GateThresholds.max_placebo_ratio`.
    placebo_ratio: float
    #: Absolute log-point divergence of two-way fixed effects from the primary, copied
    #: from the primary result so the whole battery reads from one place.
    twfe_divergence: float
    #: Worst relative movement from dropping a single post-event month.
    leave_one_out_worst: float

    #: Bias bound in log points: :data:`CONFOUNDER_STRENGTH` times the largest movement
    #: any single benchmarked covariate caused. NaN when no benchmark run succeeded.
    confounding_bound_log: float
    #: Which covariate produced that movement. The Method panel names it, because
    #: "an unmeasured confounder as strong as prior-quarter call volume" is a sentence
    #: a commercial lead can evaluate and "0.14 log points" is not.
    benchmark_covariate: str
    benchmarked: tuple[str, ...]

    #: Sampling interval widened by the bias bound, log scale. A partial-identification
    #: range, not a confidence interval - see the module docstring.
    robust_ci_low: float
    robust_ci_high: float
    #: The same range in incremental scripts, for the surface that reports money.
    robust_total_low: float
    robust_total_high: float
    #: True when the robust range excludes zero, i.e. the direction of the finding
    #: survives a confounder as strong as the strongest one measured. The single most
    #: consequential boolean in the package.
    sign_survives_bound: bool

    #: True when every estimable specification variation - including the window
    #: variations that are excluded from :attr:`spread` - agreed with the primary on the
    #: direction of the effect. This is the check that the window tests genuinely can
    #: answer: a two-month effect being smaller than a three-month one is arithmetic,
    #: but a two-month effect of the opposite sign is not, and no amount of decay
    #: explains it. Sign disagreement is a stronger signal of fragility than any
    #: magnitude ratio, because the only claim a DIRECTIONAL grade licenses is the sign.
    sign_stable_across_variants: bool = True
    #: Labels of the variations that disagreed, for the Method panel.
    sign_flips: tuple[str, ...] = ()

    warnings: tuple[str, ...] = ()

    def by_test(self, test: SensitivityTest) -> tuple[SensitivityRun, ...]:
        return tuple(run for run in self.runs if run.test is test)


def _variant_spec(spec: EstimatorSpec, **changes: object) -> EstimatorSpec:
    """``spec`` with named fields replaced and the bootstrap reduced.

    ``label`` is rewritten too. A stored variant result that carried the primary's
    label would be indistinguishable from the primary in the audit trail, and the
    fingerprint deliberately excludes ``label`` so it cannot do that job.
    """
    return dataclasses.replace(
        spec,
        label=f"{spec.label}+sensitivity",
        bootstrap_replications=VARIANT_BOOTSTRAP,
        **changes,  # type: ignore[arg-type]
    )


def _run_pipeline(
    panel: PanelFrames,
    spec: EstimatorSpec,
    *,
    cohort: Cohort | None = None,
    features: pd.DataFrame | None = None,
    propensity_columns: tuple[str, ...] | None = None,
) -> EstimatorResult:
    """Cohort to ATT under ``spec``.

    ``cohort`` and ``features`` are passed in when the variation does not change how
    the cohort is built - a different caliper reuses them, a different post window
    cannot. Rebuilding is the expensive half, so the distinction is worth making
    explicitly rather than rebuilding defensively every time.
    """
    if cohort is None:
        cohort = build_cohort(panel, spec)
    if features is None:
        features = build_features(cohort, panel)
    scores = fit_propensity(cohort, features, spec, columns=propensity_columns).scores
    matches = match_cohort(scores, features, spec)
    return estimate_att(cohort, matches, features, spec)


def _deviation(att: float, primary_att: float) -> tuple[float, bool]:
    """Relative movement from the primary, and whether it means anything."""
    if not np.isfinite(att) or not np.isfinite(primary_att):
        return float("nan"), False
    if abs(primary_att) < _MIN_PRIMARY_ATT:
        return float("nan"), False
    return abs(att - primary_att) / abs(primary_att), True


def _total_at(primary: EstimatorResult, att: float) -> float:
    """Incremental scripts implied by a log ATT, on the primary's counterfactual base.

    The estimator's incremental total is the treated arm's counterfactual baseline
    multiplied by ``exp(att) - 1``, so rescaling by that factor is exact rather than
    an approximation - and it avoids re-deriving the counterfactual baseline in a
    second place where the two could drift apart.
    """
    unit = np.exp(primary.att_log) - 1.0
    if not np.isfinite(unit) or abs(unit) < 1e-12 or not np.isfinite(att):
        return float("nan")
    return float(primary.incremental_total * (np.exp(att) - 1.0) / unit)


def _placebo(
    panel: PanelFrames, spec: EstimatorSpec, primary: EstimatorResult
) -> tuple[SensitivityRun, float]:
    """Estimate an effect between two windows that are both before the event.

    Nothing happened to these prescribers between the two windows, so an effect here is
    the machinery finding structure in noise, and its size is the scale of spurious
    effect this design manufactures.

    The arithmetic matters, and getting it wrong makes the test measure the opposite of
    what it should. Events are moved back by ``post_window_months + 1`` months, not by
    ``post_window_months``: the estimator's post window starts at offset ``+1`` because
    the event month itself is excluded (:attr:`~.spec.EstimatorSpec.post_offsets`), so a
    shift of exactly the window length lands the placebo's last post month on the real
    event month. Measured that way the placebo appeared to find 59-75% of the real
    effect, against a 35% bound - because it was partly measuring the real effect.

    The windows are then sized to fit inside the pre-event history that already exists
    rather than requiring more of it. With the default six-month baseline and six-month
    anchor there are twelve clean pre-event months; the placebo spends
    ``shift + post + pre = 4 + 3 + 3`` of them on the shifted event and its two windows,
    leaving five for the placebo's own anchor window. A textbook placebo - full-length
    windows shifted clear of the event - would need eighteen months of history and would
    refuse on every tenant's first year, which is a test that never runs.
    """
    shift = spec.post_window_months + 1
    half = spec.post_window_months
    available = spec.pre_window_months + spec.anchor_window_months
    anchor = available - shift - half
    if anchor < spec.min_anchor_months or half < 2:
        return (
            SensitivityRun(
                SensitivityTest.PLACEBO_PRE_PERIOD,
                "not attempted",
                float("nan"),
                float("nan"),
                float("nan"),
                False,
                False,
                (
                    f"the pre-event history this spec requires ({available} months) cannot "
                    f"hold a placebo that clears the event month; {shift + half * 2} months "
                    "plus an anchor window would be needed"
                ),
            ),
            float("nan"),
        )
    placebo_events = panel.events.assign(
        event_month_index=panel.events["event_month_index"].astype(int) - shift
    )
    shifted = dataclasses.replace(panel, events=placebo_events)
    variant = _variant_spec(
        spec,
        pre_window_months=half,
        post_window_months=half,
        anchor_window_months=anchor,
        min_pre_months=max(2, half - 1),
        min_post_months=max(2, half - 1),
    )
    try:
        result = _run_pipeline(shifted, variant)
    except Exception as exc:  # pragma: no cover - defensive; a refusal is preferred
        _LOG.warning("causal.sensitivity.placebo_failed", error=str(exc))
        return (
            SensitivityRun(
                SensitivityTest.PLACEBO_PRE_PERIOD,
                f"events shifted {shift} months earlier",
                float("nan"),
                float("nan"),
                float("nan"),
                False,
                False,
                f"placebo could not be run: {exc}",
            ),
            float("nan"),
        )

    ratio = (
        abs(result.att_log) / abs(primary.att_log)
        if result.estimable
        and np.isfinite(result.att_log)
        and abs(primary.att_log) >= _MIN_PRIMARY_ATT
        else float("nan")
    )
    return (
        SensitivityRun(
            SensitivityTest.PLACEBO_PRE_PERIOD,
            f"events shifted {shift} months earlier; both windows clear of the event",
            result.att_log,
            _total_at(primary, result.att_log),
            ratio,
            result.estimable,
            np.isfinite(ratio),
            "; ".join(result.warnings),
        ),
        ratio,
    )


def _leave_one_month_out(primary: EstimatorResult) -> tuple[tuple[SensitivityRun, ...], float]:
    """Drop each post-event month in turn from the cohort-time grid.

    Computed on :attr:`~.estimator.EstimatorResult.cohort_time` rather than by re-running
    the estimator, and therefore measured against the *grid's* own pooled value rather
    than against the primary ATT - the grid is unadjusted, so mixing the two scales
    would report the covariate adjustment as month sensitivity. What survives the
    comparison is the question this test is actually asking: is the effect spread across
    the post window, or is it one month?
    """
    grid = primary.cohort_time
    if grid.empty:
        return (), float("nan")
    post = grid[(grid["offset"] >= 0) & np.isfinite(grid["att_log"])]
    months = sorted(post["offset"].unique())
    if len(months) < 2:
        return (), float("nan")

    def pooled(frame: pd.DataFrame) -> float:
        weight = frame["treated_weight"].to_numpy(dtype=float)
        if weight.sum() <= 0:
            return float("nan")
        return float((frame["att_log"].to_numpy(dtype=float) * weight).sum() / weight.sum())

    full = pooled(post)
    runs: list[SensitivityRun] = []
    worst = 0.0
    for month in months:
        value = pooled(post[post["offset"] != month])
        deviation, applicable = _deviation(value, full)
        if applicable:
            worst = max(worst, deviation)
        runs.append(
            SensitivityRun(
                SensitivityTest.LEAVE_ONE_MONTH_OUT,
                f"post month +{int(month)} dropped",
                value,
                float("nan"),
                deviation,
                np.isfinite(value),
                applicable,
                "measured on the unadjusted cohort-time grid",
            )
        )
    return tuple(runs), worst


def _benchmark_covariates(propensity_importances: pd.DataFrame) -> tuple[str, ...]:
    """The most influential covariates, by the propensity model's own accounting."""
    if propensity_importances.empty or "feature" not in propensity_importances:
        return ()
    column = "gain" if "gain" in propensity_importances else propensity_importances.columns[-1]
    ordered = propensity_importances.sort_values(column, ascending=False)
    return tuple(str(name) for name in ordered["feature"].head(BENCHMARK_COVARIATES))


def run_sensitivity(
    panel: PanelFrames,
    cohort: Cohort,
    features: pd.DataFrame,
    propensity_importances: pd.DataFrame,
    primary: EstimatorResult,
    spec: EstimatorSpec,
) -> SensitivityReport:
    """Run the battery and widen the primary interval by the bias bound it finds.

    ``cohort`` and ``features`` are the primary run's, reused by every variation that
    does not change how they are built. ``propensity_importances`` is
    :attr:`~.propensity.PropensityResult.importances`, read only to decide which
    covariates to benchmark the confounder bound against.

    Returns a report even when the primary was refused: the variations are skipped, the
    bound is NaN, and :attr:`SensitivityReport.sign_survives_bound` is False. A refusal
    with an empty robustness section is a legible thing to display; an exception is not.
    """
    warnings: list[str] = []
    if not primary.estimable:
        return SensitivityReport(
            runs=(),
            spread=float("nan"),
            placebo_ratio=float("nan"),
            twfe_divergence=primary.twfe_divergence,
            leave_one_out_worst=float("nan"),
            confounding_bound_log=float("nan"),
            benchmark_covariate="",
            benchmarked=(),
            robust_ci_low=float("nan"),
            robust_ci_high=float("nan"),
            robust_total_low=float("nan"),
            robust_total_high=float("nan"),
            sign_survives_bound=False,
            warnings=("primary estimate was refused; no robustness battery was run",),
        )

    runs: list[SensitivityRun] = []
    spread = 0.0

    def record(
        test: SensitivityTest, label: str, result: EstimatorResult, *, counts: bool = True
    ) -> None:
        nonlocal spread
        deviation, applicable = _deviation(result.att_log, primary.att_log)
        if counts and applicable and result.estimable:
            spread = max(spread, deviation)
        runs.append(
            SensitivityRun(
                test,
                label,
                result.att_log,
                result.incremental_total,
                deviation,
                result.estimable,
                applicable,
                "; ".join(result.warnings),
            )
        )

    # --- specification variations ------------------------------------------
    # Caliper and control ratio change only how units are paired, so the cohort and
    # its features are reused. Post window and eligibility change which units exist
    # at all, so those rebuild.
    for value in (spec.caliper_sd / 2.0, spec.caliper_sd * 2.0):
        variant = _variant_spec(spec, caliper_sd=value, covariate_caliper_sd=value)
        record(
            SensitivityTest.ALTERNATE_CALIPER,
            f"caliper {value:.2f} SD (primary {spec.caliper_sd:.2f})",
            _run_pipeline(panel, variant, cohort=cohort, features=features),
        )

    for value in (1, spec.controls_per_treated + 2):
        if value == spec.controls_per_treated:
            continue
        variant = _variant_spec(spec, controls_per_treated=value)
        record(
            SensitivityTest.ALTERNATE_CONTROL_RATIO,
            f"{value} control(s) per attendee (primary {spec.controls_per_treated})",
            _run_pipeline(panel, variant, cohort=cohort, features=features),
        )

    # Deliberately ``counts=False``. Lengthening or shortening the accumulation window
    # changes the *estimand*, not the specification: a three-month cumulative effect and
    # a two-month one are different quantities, and under a decaying response the shorter
    # one is legitimately smaller. Measured on synthetic data where the truth is known,
    # this single test contributed deviations of 0.96 and 0.82 - by itself enough to fail
    # :attr:`~.spec.GateThresholds.max_sensitivity_spread` on a cohort whose estimate was
    # within sampling error of truth. Counting it would have graded every analysis
    # DIRECTIONAL for a reason that is not fragility. What the window variations *are*
    # good for is the sign check below and the effect-profile panel, so they are still
    # run and still reported.
    for value in (spec.post_window_months - 1, spec.post_window_months + 1):
        if value < spec.min_post_months:
            continue
        variant = _variant_spec(spec, post_window_months=value)
        record(
            SensitivityTest.ALTERNATE_POST_WINDOW,
            f"{value}-month post window (primary {spec.post_window_months})",
            _run_pipeline(panel, variant),
            counts=False,
        )

    # The brief names three control strategies but only INVITED_NON_ATTENDEE is
    # implemented, so this test varies the *eligibility rule* rather than the pool: it
    # removes prescribers who attended anything for this brand in the preceding window
    # from both arms. That is the same class of question - does the answer depend on who
    # was allowed to be a control - and it is what the data supports today. Comparing
    # pools needs a second pool to exist first.
    record(
        SensitivityTest.ALTERNATE_CONTROL_DEFINITION,
        "prior-exposure prescribers excluded from both arms",
        _run_pipeline(panel, _variant_spec(spec, exclude_prior_exposure=True)),
    )

    # --- placebo, TWFE, leave-one-month-out --------------------------------
    placebo_run, placebo_ratio = _placebo(panel, spec, primary)
    runs.append(placebo_run)

    runs.append(
        SensitivityRun(
            SensitivityTest.TWFE_CROSSCHECK,
            "two-way fixed effects on the same matched panel",
            primary.twfe_att_log,
            _total_at(primary, primary.twfe_att_log),
            *_deviation(primary.twfe_att_log, primary.att_log),
            np.isfinite(primary.twfe_att_log),
            "diagnostic only: TWFE weights cohorts in ways that can go negative",
        )
    )

    loo_runs, loo_worst = _leave_one_month_out(primary)
    runs.extend(loo_runs)

    # --- unmeasured-confounder bound ---------------------------------------
    benchmarked = _benchmark_covariates(propensity_importances)
    bound, worst_name = 0.0, ""
    for name in benchmarked:
        remaining = tuple(c for c in PROPENSITY_COLUMNS if c != name)
        if len(remaining) == len(PROPENSITY_COLUMNS) or not remaining:
            continue
        result = _run_pipeline(
            panel,
            _variant_spec(spec),
            cohort=cohort,
            features=features,
            propensity_columns=remaining,
        )
        movement = (
            abs(result.att_log - primary.att_log)
            if result.estimable and np.isfinite(result.att_log)
            else float("nan")
        )
        if np.isfinite(movement) and movement > bound:
            bound, worst_name = movement, name
        runs.append(
            SensitivityRun(
                SensitivityTest.UNMEASURED_CONFOUNDER_BOUND,
                f"{name} withheld from the propensity model",
                result.att_log,
                result.incremental_total,
                movement,
                result.estimable,
                np.isfinite(movement),
                "benchmark for the bias bound; not a specification the answer is reported under",
            )
        )

    if not benchmarked:
        warnings.append(
            "no covariate importances available, so the unmeasured-confounding bound "
            "could not be benchmarked; the reported range is sampling error only"
        )
        bound_log = float("nan")
    else:
        bound_log = CONFOUNDER_STRENGTH * bound

    # Sign agreement is taken over the specification variations only. The placebo is
    # excluded because its sign carries no information - a spurious effect may point
    # either way - and the confounder benchmarks are excluded because they are
    # deliberately misspecified models, not specifications the answer is reported under.
    _excluded = {SensitivityTest.PLACEBO_PRE_PERIOD, SensitivityTest.UNMEASURED_CONFOUNDER_BOUND}
    flips = tuple(
        run.label
        for run in runs
        if run.estimable
        and run.test not in _excluded
        and np.isfinite(run.att_log)
        and abs(run.att_log) >= _MIN_PRIMARY_ATT
        and np.sign(run.att_log) != np.sign(primary.att_log)
    )
    if flips:
        warnings.append(
            f"{len(flips)} specification variation(s) reversed the direction of the "
            f"effect ({flips[0]}); the sign itself is not stable"
        )

    widen = bound_log if np.isfinite(bound_log) else 0.0
    robust_low, robust_high = primary.ci_low - widen, primary.ci_high + widen
    survives = bool(
        np.isfinite(robust_low)
        and np.isfinite(robust_high)
        and np.isfinite(bound_log)
        and (robust_low > 0 or robust_high < 0)
    )
    if not survives and np.isfinite(bound_log):
        warnings.append(
            f"the direction of this result does not survive a confounder as strong as "
            f"{worst_name or 'the strongest measured covariate'}; treat it as directional"
        )

    report = SensitivityReport(
        runs=tuple(runs),
        spread=spread,
        placebo_ratio=placebo_ratio,
        twfe_divergence=primary.twfe_divergence,
        leave_one_out_worst=loo_worst,
        confounding_bound_log=bound_log,
        benchmark_covariate=worst_name,
        benchmarked=benchmarked,
        robust_ci_low=robust_low,
        robust_ci_high=robust_high,
        robust_total_low=_total_at(primary, robust_low),
        robust_total_high=_total_at(primary, robust_high),
        sign_survives_bound=survives,
        sign_stable_across_variants=not flips,
        sign_flips=flips,
        warnings=tuple(warnings),
    )
    _LOG.info(
        "causal.sensitivity.done",
        spec=spec.fingerprint,
        runs=len(report.runs),
        spread=spread,
        placebo_ratio=placebo_ratio,
        leave_one_out_worst=loo_worst,
        confounding_bound_log=bound_log,
        benchmark_covariate=worst_name,
        sign_survives_bound=survives,
        sign_flips=len(flips),
    )
    return report
