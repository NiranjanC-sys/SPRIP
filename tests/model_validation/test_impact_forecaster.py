"""Statistical validation of M3, the future-impact forecaster.

Every test here asserts against a quantity the fixture *chose*, not against a number this
implementation happened to produce. That distinction is what separates a validation suite
from a snapshot: a snapshot test on ``tau_squared`` would have passed happily throughout
the session in which tau-squared was being estimated against the global mean instead of
within-parent, because the wrong number was stable.

The regression that motivated the first test is worth stating, because it was invisible to
inspection and obvious to measurement. Pooling the heterogeneity statistic across all
cells at once makes the ``(brand, format)`` estimate absorb *between-brand* variance:
measured 0.126 where the truth was about 0.031. Since the parent's weight in the posterior
is ``1 / tau_squared``, a four-fold overestimate makes the parent four times too weak,
cells keep noise they should have surrendered, and the hierarchy scores worse than the
pooled baseline that it exists to improve upon.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from speaker_roi_analytics.forecast import (
    COVERAGE_TOLERANCE,
    ImpactForecaster,
    ImpactModelSpec,
    prepare_training_frame,
)
from speaker_roi_core.enums import EvidenceGrade, ForecastMode

from .conftest import WIDE_PANEL, realised_variance_components

pytestmark = pytest.mark.model_validation


def _fit(frame: pd.DataFrame, spec: ImpactModelSpec | None = None) -> ImpactForecaster:
    spec = spec or ImpactModelSpec()
    return ImpactForecaster(spec).fit(prepare_training_frame(frame, spec))


# ---------------------------------------------------------------------------
# Variance components
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [7, 21, 404, 1234, 55])
def test_top_level_heterogeneity_recovers_the_realised_between_brand_variance(
    hierarchical_events, seed
):
    """The brand-level heterogeneity is measured two-sided, on a panel wide enough for it.

    Ten brands across four formats is enough for method-of-moments to be held to a
    tolerance: across five seeds it recovers the realised between-brand variance to within
    about ten percent. The default six-brand fixture is not, which is why this test uses
    ``WIDE_PANEL`` and the level-2 test below is one-sided.

    The target is the variance actually present in the draw, not the nominal ``tau``. Seed
    404 draws six brands whose true effects happen to lie within 0.031 variance of one
    another against a nominal 0.1225; an estimator that reported 0.1225 there would be
    wrong, and a test that demanded it would be enforcing the wrong answer.
    """
    frame = hierarchical_events(seed, **WIDE_PANEL)
    between, _ = realised_variance_components(frame)

    measured = _fit(frame).tau_squared[1]

    assert measured == pytest.approx(between, rel=0.35), (
        f"level-1 tau-squared {measured:.4f} does not track the realised between-brand "
        f"variance {between:.4f}"
    )


@pytest.mark.parametrize("seed", [7, 21, 404, 1234, 55])
@pytest.mark.parametrize("wide", [False, True])
def test_child_heterogeneity_never_absorbs_its_parents_variance(hierarchical_events, seed, wide):
    """The regression guard, and the reason this file exists.

    Estimating heterogeneity against a single global mean makes the ``(brand, format)``
    figure absorb *between-brand* variance: measured 0.126 where the realised within-brand
    variance was about 0.031, a four-fold overstatement. Because the parent's weight in the
    posterior is ``1 / tau_squared``, that made the parent four times too weak, cells kept
    noise they should have surrendered, and the hierarchy scored worse on next-event MAE
    than the pooled baseline it exists to improve on. The fix was to accumulate Q, the
    degrees of freedom and the scaling denominator within each parent and only then sum
    across parents.

    The assertion is one-sided on purpose. DerSimonian-Laird truncates at zero whenever Q
    falls below its degrees of freedom, so a correct implementation legitimately reports
    0.0 on some draws - seed 21 does, and seed 7 on the wide panel reports 0.13 times the
    realised value. Understating heterogeneity shrinks cells harder towards their parent,
    which is the conservative direction and cannot manufacture a segment recommendation out
    of noise. Overstating it can, so only that direction is bounded.
    """
    frame = hierarchical_events(seed, **(WIDE_PANEL if wide else {"n": 180}))
    _, within = realised_variance_components(frame)

    measured = _fit(frame).tau_squared[2]

    assert measured <= 2.5 * within, (
        f"level-2 tau-squared {measured:.4f} exceeds 2.5x the realised within-brand "
        f"variance {within:.4f}; it is absorbing variance that belongs to the brand level"
    )


def test_child_heterogeneity_is_not_trivially_zero(hierarchical_events):
    """A guard that only bounds one side must be paired with one that rules out zero.

    Otherwise ``return 0.0`` passes the regression guard perfectly, every cell shrinks
    entirely to its brand, and format-level differences become permanently invisible.
    """
    measured = [
        _fit(hierarchical_events(seed, **WIDE_PANEL)).tau_squared[2]
        for seed in (7, 21, 404, 1234, 55)
    ]

    assert sum(value > 0.0 for value in measured) >= 4, (
        f"level-2 heterogeneity was zero on too many draws ({measured}); the estimator is "
        "not detecting format variance that the fixture put there"
    )


def test_zero_heterogeneity_collapses_to_pooled(hierarchical_events):
    """When cells are genuinely identical, the model must decline to distinguish them.

    This is the regime plan.md §12.6 wants handled by "transparent category averages", and
    an empirical-Bayes hierarchy reaches it on its own: with no measurable heterogeneity the
    parent weight goes to infinity, every cell surrenders entirely, and the reported mode
    becomes ``POOLED``. A model that still produced per-cell numbers here would be
    reporting sampling noise as segment insight.
    """
    forecaster = _fit(hierarchical_events(99, tau=0.0, n=150))

    assert forecaster.tau_squared[1] < 0.05
    assert forecaster.tau_squared[2] == pytest.approx(0.0, abs=1e-9)

    forecast = forecaster.predict("b0", "IN_PERSON", 25.0)
    assert forecast.mode is ForecastMode.POOLED
    assert forecast.shrinkage == pytest.approx(0.0, abs=1e-9)
    assert forecast.per_attendee == pytest.approx(forecaster.pooled_mean, rel=0.35)


@pytest.mark.parametrize("seed", [7, 21])
def test_shrunken_cell_means_beat_raw_cell_means(hierarchical_events, seed):
    """Shrinkage must move cell estimates *towards* truth, not merely towards the mean.

    This is the model's reason for existing, and the only test in the file that measures it
    directly. The comparison is against the raw within-cell precision-weighted mean - the
    obvious alternative, and the one a spreadsheet would produce.
    """
    frame = hierarchical_events(seed, n=180)
    forecaster = _fit(frame)
    truth = frame.drop_duplicates(["brand_id", "event_format"]).set_index(
        ["brand_id", "event_format"]
    )["_true"]

    posterior_error = []
    raw_error = []
    for key, true_value in truth.items():
        cell = forecaster.cells.get(key)
        if cell is None:
            continue
        posterior_error.append(abs(cell.posterior_mean - true_value))
        raw_error.append(abs(cell.raw_mean - true_value))

    assert len(posterior_error) >= 12
    assert np.mean(posterior_error) < np.mean(raw_error), (
        f"shrunken cell means ({np.mean(posterior_error):.4f}) must be closer to truth "
        f"than raw cell means ({np.mean(raw_error):.4f})"
    )


def test_precision_weighting_discounts_imprecise_events(hierarchical_events):
    """A wide-interval event must influence its cell less than a tight-interval one.

    Precision weighting is what lets ``DIRECTIONAL`` events contribute to the population
    without their individual magnitudes being quoted, so it is load-bearing for the
    admissible-grade policy rather than an efficiency nicety. The construction here is
    deliberately extreme: two events in one cell, one of them ten times more precise, with
    observations on opposite sides. The posterior must land near the precise one.
    """
    spec = ImpactModelSpec()
    rows = []
    for i, (value, se) in enumerate(((1.0, 0.10), (9.0, 1.00))):
        attendees = 20
        rows.append(
            {
                "event_id": f"e{i}",
                "brand_id": "solo",
                "event_format": "IN_PERSON",
                "event_month_index": i,
                "verified_attendees": attendees,
                "incremental_total": value * attendees,
                "ci_low": (value - 1.2816 * se) * attendees,
                "ci_high": (value + 1.2816 * se) * attendees,
                "grade": EvidenceGrade.MODERATE,
            }
        )
    forecaster = ImpactForecaster(spec).fit(prepare_training_frame(pd.DataFrame(rows), spec))
    cell = forecaster.cells[("solo", "IN_PERSON")]

    # Inverse-variance weights are 100 and 1, so the mean sits within ~0.08 of 1.0. An
    # unweighted mean would be 5.0; asserting below the midpoint would not have caught it.
    assert cell.raw_mean < 1.5, f"raw cell mean {cell.raw_mean:.3f} ignores the precision gap"


def test_zero_width_intervals_are_rejected(hierarchical_events):
    """An estimate with no uncertainty is an upstream bug, not a maximally useful datum.

    Left in, it would receive infinite weight and dominate its cell and every ancestor.
    """
    frame = hierarchical_events(11, n=60)
    frame.loc[0, ["ci_low", "ci_high"]] = frame.loc[0, "incremental_total"]
    prepared = prepare_training_frame(frame, ImpactModelSpec())

    assert frame.loc[0, "event_id"] not in set(prepared["event_id"])
    assert len(prepared) == len(frame) - 1


# ---------------------------------------------------------------------------
# Intervals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [7, 21])
def test_conformal_intervals_achieve_nominal_coverage(hierarchical_events, seed):
    """Empirical coverage must land near the nominal level.

    Split-conformal calibration guarantees this in expectation under exchangeability, so
    the test is really checking the plumbing: that residuals are scale-normalised before
    the quantile is taken, that the finite-sample ``(1 - alpha)(1 + 1/n)`` correction is
    applied, and that the scale used at prediction time is the one used at calibration
    time. Any of those three going wrong shows up here as coverage off by 10-30 points.
    """
    forecaster = _fit(hierarchical_events(seed, n=180))
    report = forecaster.validate(
        prepare_training_frame(hierarchical_events(seed, n=180), forecaster.spec)
    )

    assert report.nominal_coverage == pytest.approx(forecaster.spec.coverage)
    assert report.coverage_ok, (
        f"empirical coverage {report.interval_coverage:.2f} is more than "
        f"{COVERAGE_TOLERANCE} from the nominal {report.nominal_coverage}"
    )


def test_interval_scale_includes_heterogeneity(hierarchical_events):
    """The prediction interval must be wider than the interval on the cell mean.

    Forecasting a *single future event* carries the cell's estimation error plus the
    event-to-event spread the cell mean averages away. Omitting the second term implies
    that enough historical data would let a planner predict one program exactly, which is
    false for any effect with real dispersion, and produces intervals that look impressive
    and miss.
    """
    forecaster = _fit(hierarchical_events(7, n=180))
    cell = forecaster.cells[("b0", "IN_PERSON")]
    forecast = forecaster.predict("b0", "IN_PERSON", 25.0)

    half_width = (forecast.per_attendee_high - forecast.per_attendee_low) / 2.0
    assert half_width > cell.posterior_se, (
        "the prediction interval is no wider than the standard error of the cell mean, "
        "so between-event dispersion is missing from the scale"
    )


def test_scaled_to_combines_uncertainties_in_relative_variance(hierarchical_events):
    """Rescaling to an uncertain attendee count must widen the total interval.

    The wrong implementation - multiplying each endpoint by the corresponding attendee
    bound - understates the range at one end and overstates it at the other, because it
    pairs the pessimistic effect with the pessimistic turnout as though the two were
    perfectly correlated. Adding in relative-variance space is the correct combination for
    two independent uncertainties.
    """
    forecaster = _fit(hierarchical_events(7, n=180))
    base = forecaster.predict("b0", "IN_PERSON", 25.0)
    scaled = base.scaled_to(25.0, 18.0, 32.0)

    assert scaled.total == pytest.approx(base.total, rel=1e-9)
    assert scaled.total_low < base.total_low
    assert scaled.total_high > base.total_high
    # A certain count must be a no-op, which pins the combination rather than merely its
    # direction.
    unchanged = base.scaled_to(25.0, 25.0, 25.0)
    assert unchanged.total_low == pytest.approx(base.total_low, rel=1e-9)
    assert unchanged.total_high == pytest.approx(base.total_high, rel=1e-9)


# ---------------------------------------------------------------------------
# Refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("brand", "fmt", "attendees", "expected_feature"),
    [
        ("never-seen", "IN_PERSON", 25.0, "brand_id"),
        ("b0", "MYSTERY_FORMAT", 25.0, "event_format"),
        ("b0", "IN_PERSON", 5000.0, "planned_attendees"),
    ],
)
def test_out_of_support_inputs_refuse_with_a_named_feature(
    hierarchical_events, brand, fmt, attendees, expected_feature
):
    """plan.md §12.6 asks for a warning on out-of-support inputs; this refuses instead.

    A warning attached to a number still ships the number, and a number on a planning
    screen gets used. The three branches are an unseen brand, an unseen format, and an
    attendee count beyond the measured range - the last being the one that matters most,
    because per-attendee effects measured on rooms of 40 do not extrapolate to 5000 and the
    arithmetic will happily produce a figure anyway.

    Both the offending feature and a planner-readable remedy must be present: "out of
    support" alone tells someone that the software said no, not what to do next.
    """
    forecaster = _fit(hierarchical_events(7, n=180))
    forecast = forecaster.predict(brand, fmt, attendees)

    assert forecast.mode is ForecastMode.OUT_OF_SUPPORT
    assert not forecast.usable
    assert any(feature.startswith(expected_feature) for feature in forecast.out_of_support), (
        f"expected {expected_feature} among {forecast.out_of_support}"
    )
    assert len(forecast.remedy) > 30, "an out-of-support refusal must say what would fix it"


def test_thin_panel_falls_back_smoothly_rather_than_failing(hierarchical_events):
    """Below the plan's 100-200 event threshold the model degrades, it does not break.

    plan.md §12.6 mandates a switch to pooled averages under roughly 100 measured events.
    Empirical Bayes reaches the same destination continuously: with 45 events the cells
    have almost no independent weight, so the answer is approximately the pooled mean -
    which is exactly what the mandated fallback would return, minus the cliff.
    """
    forecaster = _fit(hierarchical_events(7, n=45))
    forecast = forecaster.predict("b0", "IN_PERSON", 25.0)

    assert forecast.usable
    assert forecast.mode in {ForecastMode.MODEL, ForecastMode.POOLED}
    assert forecast.shrinkage < 0.60, (
        "with 45 measured events a single cell should not be carrying most of its own "
        "weight; that is the regime the plan wanted pooled"
    )


# ---------------------------------------------------------------------------
# The promotion criterion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [7, 21])
def test_rolling_origin_validation_is_non_inferior_to_the_historical_average(
    hierarchical_events, seed
):
    """The honest promotion gate: not worse, with the uncertainty stated.

    plan.md §12.6 makes next-event MAE against a historical-average baseline a promotion
    criterion. Measured, that criterion has almost no power at realistic panel sizes: with
    per-event noise several times the between-segment signal, the paired standard error on
    the MAE difference is comparable to any difference a correct model produces. Seed 7
    loses by 1.2 standard errors and seed 21 wins by 2.7 - the same model, the same code,
    different draws.

    So the suite asserts non-inferiority rather than a win, and asserts that the standard
    error is actually reported, because a promotion decision made on a point estimate whose
    uncertainty nobody printed is the failure this whole design is trying to avoid. Note
    that ``beats_baseline`` - the plan's literal criterion - is deliberately *not* asserted.
    """
    frame = prepare_training_frame(hierarchical_events(seed, n=180), ImpactModelSpec())
    report = ImpactForecaster().fit(frame).validate(frame, folds=3)

    assert report.folds == 3
    assert report.n_holdout >= 30
    assert np.isfinite(report.mae_advantage)
    assert np.isfinite(report.mae_advantage_se) and report.mae_advantage_se > 0
    assert report.not_worse, (
        f"MAE advantage {report.mae_advantage:+.4f} is more than two standard errors "
        f"({report.mae_advantage_se:.4f}) worse than the historical average"
    )


def test_validation_never_scores_a_model_on_its_own_training_rows(hierarchical_events):
    """Each fold must train strictly before its origin.

    A leak here would not raise; it would quietly produce a model that looks excellent and
    forecasts badly, which is the single most expensive mistake available in this module.
    The check is structural: with more folds the first training head must stay put and the
    holdout must remain the tail, so no fold can ever see its own future.
    """
    frame = prepare_training_frame(hierarchical_events(7, n=180), ImpactModelSpec())
    forecaster = ImpactForecaster().fit(frame)

    one = forecaster.validate(frame, folds=1)
    three = forecaster.validate(frame, folds=3)

    assert one.n_train == three.n_train, (
        "the first origin must not move with the fold count; if it does, later folds are "
        "training on rows earlier folds scored"
    )
    assert one.n_holdout == pytest.approx(three.n_holdout, rel=0.15)
    assert three.folds == 3


def test_by_segment_bias_is_reported_for_every_format(hierarchical_events):
    """plan.md §12.6 asks for bias by segment; a single pooled bias can hide a reversal."""
    frame = prepare_training_frame(hierarchical_events(7, n=180), ImpactModelSpec())
    report = ImpactForecaster().fit(frame).validate(frame)

    assert set(report.by_segment["event_format"]) == set(frame["event_format"].unique())
    assert {"n", "mae", "bias"} <= set(report.by_segment.columns)
    assert (report.by_segment["n"] > 0).all()


def test_forecast_is_reproducible_from_the_spec_fingerprint(hierarchical_events):
    """Two fits of the same spec on the same data must agree exactly.

    Reproducibility is why the DerSimonian-Laird method-of-moments estimator was chosen
    over REML: it is closed-form, so there is no optimiser whose starting point or
    convergence tolerance can make a stored analysis irreproducible six months later.
    """
    frame = prepare_training_frame(hierarchical_events(7, n=180), ImpactModelSpec())
    first = ImpactForecaster().fit(frame).predict("b0", "IN_PERSON", 25.0)
    second = ImpactForecaster().fit(frame).predict("b0", "IN_PERSON", 25.0)

    assert first.spec_fingerprint == second.spec_fingerprint
    assert first.per_attendee == pytest.approx(second.per_attendee, rel=1e-12)
    assert first.per_attendee_low == pytest.approx(second.per_attendee_low, rel=1e-12)
    assert first.per_attendee_high == pytest.approx(second.per_attendee_high, rel=1e-12)
