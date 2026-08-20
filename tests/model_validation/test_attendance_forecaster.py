"""Statistical validation of M4, the attendance and reach forecaster.

M4 is a *different statistical situation* from M3 and is tested differently. M3 has a few
dozen noisy observations of a quantity that cannot be observed directly; M4 has tens of
thousands of clean binary outcomes of a quantity that is observed the day after the event.
So M4 gets a gradient-boosted learner and is held to discrimination, calibration and
interval coverage, while M3 gets a closed-form hierarchy and is held to variance recovery.

The property this file guards hardest is **calibration, not discrimination**. Reach is
forecast by summing predicted attendance probabilities, so a model with a superb AUC that
reports 0.9 where the truth is 0.3 ranks every invitee perfectly and forecasts the room
three times over. AUC is invariant to any monotone transform of the scores; the number the
planner actually reads is not.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from speaker_roi_analytics.forecast import (
    AttendanceForecaster,
    AttendanceModelSpec,
)
from speaker_roi_core.enums import ForecastMode

from .conftest import build_invitations

pytestmark = [pytest.mark.model_validation, pytest.mark.slow]


@pytest.fixture(scope="module")
def fitted() -> tuple[AttendanceForecaster, pd.DataFrame, pd.DataFrame]:
    """Fitted once for the module: LightGBM on 3,600 invitations is not free.

    Module scope is safe here only because every test below treats the forecaster as
    read-only. Any test that refits must build its own.
    """
    invitations, events = build_invitations(20260819, n_events=90)
    forecaster = AttendanceForecaster(AttendanceModelSpec()).fit(invitations, events)
    return forecaster, invitations, events


# ---------------------------------------------------------------------------
# Discrimination and calibration
# ---------------------------------------------------------------------------


def test_model_discriminates_better_than_chance(fitted):
    """A floor, not a target.

    The fixture's outcome is generated from a logistic model on four of the eleven fitted
    features plus a per-event shock that no feature can see, so the achievable AUC is well
    short of one. The assertion is deliberately loose: its job is to catch a feature matrix
    that got shuffled relative to its labels, which is the failure that produces a
    beautifully calibrated, entirely useless model.
    """
    forecaster, invitations, events = fitted
    report = forecaster.validate(invitations, events)

    assert report.auc > 0.60, f"AUC {report.auc:.3f} is barely better than chance"
    assert report.brier < report.baseline_brier, (
        f"Brier score {report.brier:.4f} is no better than predicting the base rate "
        f"({report.baseline_brier:.4f})"
    )


def test_probabilities_are_calibrated_not_merely_ranked(fitted):
    """The load-bearing test for reach forecasting.

    A calibration slope near one means that among invitations predicted at 30%, close to
    30% attend. Summing calibrated probabilities is then the correct expected count, which
    is exactly what :meth:`forecast_reach` does. A slope of 0.5 would mean the model's
    spread is twice too wide and every large room is over-forecast, with no effect at all on
    AUC.
    """
    forecaster, invitations, events = fitted
    report = forecaster.validate(invitations, events)

    assert report.calibration_slope == pytest.approx(1.0, abs=0.35), (
        f"calibration slope {report.calibration_slope:.3f} is far from one; predicted "
        "probabilities do not mean what they say"
    )


def test_summed_probabilities_track_realised_attendance(fitted):
    """Reach must be right in aggregate, which is the only grain a planner books against.

    Event-level MAE against the historical mean attendance is plan.md's baseline. Unlike
    M3's per-event effect, this comparison has real power: the outcome is observed without
    noise, and there are thousands of invitations behind each event total.
    """
    forecaster, invitations, events = fitted
    report = forecaster.validate(invitations, events)

    assert report.event_mae < report.baseline_event_mae, (
        f"event-total MAE {report.event_mae:.2f} does not beat the historical-average "
        f"baseline {report.baseline_event_mae:.2f}"
    )
    assert report.beats_baseline


def test_isotonic_calibration_is_monotone_and_bounded():
    """The calibration map must be a non-decreasing function into [0, 1].

    Hand-rolled pool-adjacent-violators rather than scikit-learn's estimator, so that the
    map serialises as two inspectable arrays instead of a pickle. Hand-rolled means it needs
    its own test: a PAV implementation that stops pooling one iteration early leaves a
    single inversion, which is invisible in aggregate metrics and reorders individual HCPs.
    """
    from speaker_roi_analytics.forecast.attendance import _apply_isotonic, _isotonic

    rng = np.random.default_rng(3)
    scores = np.sort(rng.random(500))
    # Deliberately mis-scaled truth: the map must undo the compression, not preserve it.
    outcomes = (rng.random(500) < (0.15 + 0.5 * scores)).astype(float)

    thresholds, values = _isotonic(scores, outcomes)

    assert np.all(np.diff(values) >= -1e-12), "calibration map is not monotone"
    assert values.min() >= 0.0 and values.max() <= 1.0
    assert np.all(np.diff(thresholds) >= -1e-12), "calibration thresholds are unsorted"

    mapped = _apply_isotonic(np.array([0.0, 0.25, 0.5, 0.75, 1.0]), thresholds, values)
    assert np.all(np.diff(mapped) >= -1e-12)
    assert np.all((mapped >= 0.0) & (mapped <= 1.0))


def test_auc_handles_ties_without_bias():
    """A constant predictor must score exactly 0.5, not 0.0 or 1.0.

    Tie handling is where hand-written AUC implementations usually break, and a degenerate
    tree stump that predicts one value for every row is a real outcome on a thin panel. An
    implementation that resolved ties by input order would report a perfect or a hopeless
    AUC depending on how the frame happened to be sorted.
    """
    from speaker_roi_analytics.forecast.attendance import _auc

    outcomes = np.array([0, 1, 0, 1, 1, 0, 0, 1], dtype=float)
    constant = np.full_like(outcomes, 0.42)

    assert _auc(constant, outcomes) == pytest.approx(0.5, abs=1e-12)
    assert _auc(outcomes, outcomes) == pytest.approx(1.0, abs=1e-12)
    assert _auc(-outcomes, outcomes) == pytest.approx(0.0, abs=1e-12)
    # Half the rows tied, half perfectly separated: strictly between the two.
    partial = np.array([0.0, 1.0, 0.5, 0.5, 0.5, 0.0, 0.0, 1.0])
    assert 0.5 < _auc(partial, outcomes) < 1.0


# ---------------------------------------------------------------------------
# Intervals
# ---------------------------------------------------------------------------


def test_reach_interval_reflects_shared_shocks_not_binomial_variance(fitted):
    """The interval must be wide enough for the dispersion the features cannot see.

    Treating 2,000 invitations as independent Bernoulli draws gives a standard deviation of
    roughly twenty attendees on a thousand-person forecast - about two percent - which would
    be spectacularly overconfident. Whether a room fills is dominated by shocks no
    per-invitation feature captures: weather, a competing congress, a rep who did not call.
    The fixture injects exactly such a shock, so a binomial interval fails here as it would
    in production.
    """
    forecaster, invitations, _ = fitted
    subset = invitations[invitations["event_id"].isin({"e0", "e1", "e2"})]

    reach = forecaster.forecast_reach(subset)
    probabilities = forecaster.score_invitations(subset)["attendance_probability"].to_numpy()
    half_width = (reach.high - reach.low) / 2.0
    binomial_sd = float(np.sqrt((probabilities * (1.0 - probabilities)).sum()))

    assert half_width > 1.5 * binomial_sd, (
        f"interval half-width {half_width:.1f} is close to the binomial standard deviation "
        f"{binomial_sd:.1f}; between-event dispersion is missing"
    )
    assert reach.low >= 0.0, "a negative attendance floor is not a forecast"


def test_reach_interval_covers_realised_totals(fitted):
    """Nominal coverage, measured on held-out events."""
    forecaster, invitations, events = fitted
    report = forecaster.validate(invitations, events)

    assert report.interval_coverage >= forecaster.spec.coverage - 0.20, (
        f"empirical interval coverage {report.interval_coverage:.2f} is far below the "
        f"nominal {forecaster.spec.coverage}"
    )


def test_design_forecast_respects_venue_capacity(fitted):
    """A forecast above the capacity of the room is arithmetic, not a prediction."""
    forecaster, _, _ = fitted

    design = {
        "invitations_planned": 110,
        "days_notice": 45,
        "is_virtual": 0,
        "format_rank": 1,
        "speaker_prior_events": 5,
        "month_of_year": 6,
        "is_weekend": 0,
        "venue_capacity": 60,
    }
    forecast = forecaster.forecast_design(design)

    assert forecast.expected_attendees <= 60.0
    assert forecast.high <= 60.0
    assert any("capacity" in w or "ceiling" in w for w in forecast.warnings), (
        f"a capacity-limited forecast must say so, got {forecast.warnings}"
    )


def test_feature_drift_warns_rather_than_refuses(fitted):
    """M4 warns where M3 refuses, and the asymmetry is deliberate.

    An out-of-support per-attendee *effect* extrapolates a causal quantity and can invent
    money, so M3 refuses. An out-of-range invitation count extrapolates a turnout rate,
    which degrades gracefully and still beats the planner's alternative of guessing. So this
    reports drift and continues.
    """
    forecaster, invitations, _ = fitted
    drifted = invitations[invitations["event_id"] == "e0"].copy()
    drifted["days_notice"] = 9999
    drifted["distance_km"] = 50_000.0

    reach = forecaster.forecast_reach(drifted)

    assert reach.warnings, "features far outside the fitted range must be reported"
    assert np.isfinite(reach.expected_attendees)
    assert 0.0 <= reach.expected_attendees <= len(drifted)


# ---------------------------------------------------------------------------
# The prohibition in plan.md §15
# ---------------------------------------------------------------------------


def test_invitation_scores_never_expose_a_prescribing_ranking(fitted):
    """plan.md §15 prohibits named-HCP prescribing rankings for speaker selection.

    The prohibition is enforced by the return type rather than by a policy document:
    :meth:`score_invitations` returns attendance probability and nothing else, so there is
    no column an integrator could mistake for prescribing value, and no way to build the
    prohibited ranking from what this model hands back. Adding a decile or an effect column
    here would be the whole violation, which is why the assertion is on the exact column
    set rather than on the absence of particular names.
    """
    forecaster, invitations, _ = fitted
    scored = forecaster.score_invitations(invitations[invitations["event_id"] == "e0"])

    assert set(scored.columns) == {"event_id", "hcp_id", "attendance_probability"}
    assert scored["attendance_probability"].between(0.0, 1.0).all()


def test_validation_split_never_divides_a_single_event(fitted):
    """Invitations from one event must land wholly in train or wholly in holdout.

    Splitting an event across the boundary leaks its shared shock: the model sees how many
    of that room's invitees attended and is then asked to predict the rest, which is not a
    question anyone will ever ask it. plan.md §12.6's "entire-event grouping" says the same
    thing about M3; it applies with more force here, because the shock is the dominant term.
    """
    forecaster, invitations, events = fitted
    report = forecaster.validate(invitations, events)

    total = report.n_train_invitations + report.n_holdout_invitations
    assert total == len(invitations), "every invitation must be in exactly one side"
    # Room sizes vary, so the check is that the holdout count is expressible as a sum of
    # whole trailing events: the split is temporal, so the holdout is a suffix of the event
    # order, and its invitation count must match one of those suffixes exactly.
    sizes = invitations.groupby("event_id").size()
    order = events.sort_values("event_month_index")["event_id"]
    suffix_totals = {int(sizes.reindex(order[k:]).sum()) for k in range(len(order) + 1)}
    assert report.n_holdout_invitations in suffix_totals, (
        f"{report.n_holdout_invitations} holdout invitations is not a whole number of "
        "trailing events; the split cut through an event"
    )


def test_design_far_outside_the_fitted_range_falls_back_to_the_historical_rate(fitted):
    """A boosted tree does not extrapolate, it saturates - and that is worse than refusing.

    Asked about 4,000 invitations after being fitted on rooms of 18 to 120, the regressor
    returns the mean of its highest leaf: about the attendance of a 120-person program, for
    a program forty times that size, with no indication that anything is wrong. That is a
    silently wrong number on a planning screen, which is the failure mode this whole
    codebase is organised against.

    The historical attendance rate does extrapolate. Badly, but monotonically and visibly -
    twice the invitations gives twice the expected attendance - so an out-of-range design is
    answered from the rate, labelled ``POOLED``, and told why.
    """
    forecaster, _, _ = fitted
    design = {
        "invitations_planned": 4000,
        "days_notice": 45,
        "is_virtual": 0,
        "format_rank": 1,
        "speaker_prior_events": 5,
        "month_of_year": 6,
        "is_weekend": 0,
        "venue_capacity": 5000,
    }
    forecast = forecaster.forecast_design(design)

    assert forecast.mode is ForecastMode.POOLED
    assert forecast.expected_attendees == pytest.approx(
        4000 * forecaster.historical_rate, rel=1e-9
    ), "an out-of-range design must be answered from the rate, not from a saturated tree"
    assert any("outside the range" in w for w in forecast.warnings), forecast.warnings
    # The saturated tree would have answered with something near a large in-range program.
    assert forecast.expected_attendees > 200


def test_interval_width_scales_with_room_size(fitted):
    """Dispersion is proportional, so the interval must grow with the forecast.

    Shared shocks act on the attendance *rate*, so their effect on the headcount scales with
    the room. An absolute standard deviation measured on 40-person programs and applied
    unchanged to a 400-person one under-covers it by an order of magnitude, and over-covers
    a 10-person one just as badly - which is what produced 55% empirical coverage against a
    nominal 80% before the dispersion estimate was made relative.

    The assertion is on the *relative* half-width narrowing while the absolute one widens.
    Both directions matter: proportional-only dispersion would keep the relative width flat,
    and absolute-only would keep the absolute width flat.
    """
    forecaster, invitations, _ = fitted
    by_size = invitations.groupby("event_id").size().sort_values()
    small = forecaster.forecast_reach(invitations[invitations["event_id"] == by_size.index[0]])
    large = forecaster.forecast_reach(invitations[invitations["event_id"] == by_size.index[-1]])

    small_half = (small.high - small.low) / 2.0
    large_half = (large.high - large.low) / 2.0

    assert large.expected_attendees > 2.0 * small.expected_attendees, (
        "the fixture must contain rooms of materially different sizes for this to mean anything"
    )
    assert large_half > small_half, (
        f"a {large.expected_attendees:.0f}-attendee forecast has a half-width of "
        f"{large_half:.1f} against {small_half:.1f} for {small.expected_attendees:.0f}; "
        "dispersion is not scaling with the room"
    )
    # The binomial floor is added in variance, so the relative width falls with size rather
    # than staying constant. Flat relative width would mean the floor was dropped.
    assert large_half / large.expected_attendees < small_half / small.expected_attendees
