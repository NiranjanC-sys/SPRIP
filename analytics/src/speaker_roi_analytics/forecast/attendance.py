"""M4: forecasting verified attendance and reach for a proposed event design.

This is the other half of a forward-looking answer, and it is a genuinely different
statistical problem from :mod:`.impact`. Where the impact model has scores of expensive
rows and must shrink hard, this model has one row per *invitation* - thousands of them
per tenant per year - and a directly observed outcome that nobody had to estimate. That
abundance is what makes a gradient-boosted learner appropriate here and inappropriate
there, and the asymmetry is deliberate rather than inconsistent.

Two targets, not one
--------------------
plan.md talks about forecasting "attendance", which conflates two questions a planner
asks separately:

**Reach** - how many of the invited will show up. Predicted per invitation as a
probability, then summed over the invitation list. Summing calibrated probabilities is
the correct way to get an expected count, and it is why calibration matters more here
than discrimination: a model with a superb AUC that reports every probability as 0.9 when
the truth is 0.3 ranks prospects perfectly and forecasts attendance three times over.

**Composition** - *who* shows up. A program that hits its headcount entirely from
prescribers who would have written anyway is not the same program, and since
:mod:`.impact` forecasts effect per attendee within a segment, the composition forecast
is what makes the two models compose. It is returned as an expected-attendee breakdown
across whatever segment column the caller names.

Why Tweedie rather than binary classification, at the event level
-----------------------------------------------------------------
The per-invitation model is an ordinary binary classifier. The *event-level* model - used
when an event's invitation list does not exist yet, only its design - regresses verified
attendance directly, and there the distribution matters: attendance is a non-negative
count with a substantial mass at zero (cancelled and failed programs) and a long right
tail. Squared-error loss on that shape produces negative predictions for small events and
systematically underestimates large ones. Tweedie loss with power 1.3 is built for
exactly this compound-Poisson-gamma shape, and it keeps predictions non-negative by
construction rather than by clipping.

What this model must never be used for
--------------------------------------
The per-invitation probabilities rank named prescribers by likelihood of attending. That
ranking is legitimate for logistics - who to remind, how many to invite to fill a room -
and plan.md §15 forbids using anything of this kind to build a named-HCP prescribing
ranking for speaker or attendee selection. The distinction is enforced by what this module
returns: :class:`ReachForecast` exposes per-invitation scores only as an aggregate and a
segment breakdown, and :meth:`AttendanceForecaster.score_invitations` exists but is
documented as logistics-only and never carries an outcome or value column alongside the
score. Making the prescribing-weighted ranking inconvenient is not the same as preventing
it, but it does mean the join has to be written deliberately by someone who can be asked
why.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import structlog

from speaker_roi_core.enums import ForecastMode

__all__ = [
    "EVENT_FEATURES",
    "INVITATION_FEATURES",
    "MIN_EVENTS_FOR_EVENT_MODEL",
    "MIN_INVITATIONS",
    "AttendanceForecast",
    "AttendanceForecaster",
    "AttendanceModelSpec",
    "ReachForecast",
    "ReachValidation",
]

_LOG = structlog.get_logger(__name__)

#: Per-invitation features. Every one is knowable at the moment the invitation is sent -
#: this is the same leakage discipline :func:`..causal.features.assert_no_leakage`
#: enforces, for the same reason: a feature recorded after the event predicts attendance
#: perfectly and forecasts nothing.
INVITATION_FEATURES: tuple[str, ...] = (
    "days_notice",
    "channel_rank",
    "prior_invitations",
    "prior_attendance_rate",
    "distance_km",
    "is_virtual",
    "specialty_rank",
    "decile",
    "prior_rep_calls",
    "month_of_year",
    "is_weekend",
)

#: Event-design features for the cold-start model, used before an invitation list exists.
EVENT_FEATURES: tuple[str, ...] = (
    "invitations_planned",
    "days_notice",
    "is_virtual",
    "format_rank",
    "speaker_prior_events",
    "month_of_year",
    "is_weekend",
    "venue_capacity",
)

#: Invitations below which the per-invitation model is not fitted. LightGBM will happily
#: fit 200 rows and produce probabilities that look calibrated on their own training data.
MIN_INVITATIONS = 2_000

#: Events below which the cold-start model falls back to a historical attendance *rate*
#: applied to the planned invitation count. That fallback is what a planner does by hand,
#: and it is a respectable predictor.
MIN_EVENTS_FOR_EVENT_MODEL = 60


@dataclass(frozen=True, slots=True)
class AttendanceModelSpec:
    """Versioned configuration for both sub-models."""

    label: str = "attendance-v1"
    #: Tweedie variance power for the event-level model. 1.3 sits between Poisson (1.0)
    #: and gamma (2.0), which is where zero-inflated counts with a long tail live. Not
    #: tuned per tenant: a power fitted on 60 events would be fitted to their noise, and
    #: the loss is not sensitive enough over 1.1-1.5 to be worth the overfitting risk.
    tweedie_power: float = 1.3
    learning_rate: float = 0.05
    num_leaves: int = 15
    min_data_in_leaf: int = 40
    n_estimators: int = 300
    #: Temporal holdout share, by event. Events rather than invitations so that no
    #: event's invitations straddle the split - the same entire-event grouping rule
    #: :mod:`.impact` follows, and for the same reason.
    holdout_share: float = 0.25
    coverage: float = 0.80
    #: Isotonic calibration of the per-invitation probabilities before they are summed.
    #: On by default because the sum is the deliverable and an uncalibrated sum is wrong
    #: even when the ranking is perfect - see the module docstring.
    calibrate: bool = True
    random_state: int = 20260819

    @property
    def fingerprint(self) -> str:
        return "|".join(
            (
                f"tw{self.tweedie_power:.2f}",
                f"lr{self.learning_rate:.3f}",
                f"lv{self.num_leaves}",
                f"md{self.min_data_in_leaf}",
                f"ne{self.n_estimators}",
                f"ho{self.holdout_share:.2f}",
                f"cal{int(self.calibrate)}",
                f"rs{self.random_state}",
            )
        )


@dataclass(frozen=True, slots=True)
class ReachForecast:
    """Expected verified attendance for a known invitation list."""

    mode: ForecastMode
    expected_attendees: float
    low: float
    high: float
    coverage: float
    n_invitations: int
    #: Expected attendees by segment. The composition half of the answer; empty when no
    #: segment column was requested.
    by_segment: pd.DataFrame = field(default_factory=pd.DataFrame)
    #: Mean predicted probability. Reported because it is the number a planner can sanity
    #: check against their own experience in a way a total cannot.
    mean_probability: float = float("nan")
    out_of_support: tuple[str, ...] = ()
    remedy: str = ""
    spec_fingerprint: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        return self.mode is not ForecastMode.OUT_OF_SUPPORT


@dataclass(frozen=True, slots=True)
class AttendanceForecast:
    """Expected verified attendance for a design with no invitation list yet."""

    mode: ForecastMode
    expected_attendees: float
    low: float
    high: float
    coverage: float
    #: Expected attendees divided by planned invitations. The interpretable form, and the
    #: one that transfers across event sizes.
    implied_rate: float
    out_of_support: tuple[str, ...] = ()
    remedy: str = ""
    spec_fingerprint: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        return self.mode is not ForecastMode.OUT_OF_SUPPORT


@dataclass(frozen=True, slots=True)
class ReachValidation:
    """Holdout performance for both sub-models.

    Discrimination and calibration are reported separately and neither substitutes for
    the other. AUC answers "does it rank the right people higher"; the calibration slope
    and the event-level attendance error answer "does the total mean anything". A model
    can be excellent at one and useless at the other, and only the second determines
    whether a planner's headcount is right.
    """

    n_train_invitations: int
    n_holdout_invitations: int
    auc: float
    #: Slope of observed attendance on predicted probability, in deciles. 1.0 is perfect;
    #: below 1.0 means the model is over-confident at the extremes.
    calibration_slope: float
    brier: float
    baseline_brier: float
    #: Absolute error in expected headcount, averaged over holdout events, alongside the
    #: same figure for a flat historical-rate baseline.
    event_mae: float
    baseline_event_mae: float
    interval_coverage: float
    by_segment: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def beats_baseline(self) -> bool:
        return (
            np.isfinite(self.event_mae)
            and np.isfinite(self.baseline_event_mae)
            and self.event_mae < self.baseline_event_mae
        )


def _z_for(coverage: float) -> float:
    """Two-sided normal quantile for a coverage level.

    Interpolated from a small table rather than pulled from ``scipy.stats`` so that the
    analytics package keeps no runtime dependency on scipy for a lookup, and so that an
    unrecognised coverage level produces a defensible number instead of an exception in a
    forecast path.
    """
    table = {0.50: 0.6745, 0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}
    if coverage in table:
        return table[coverage]
    levels = sorted(table)
    return float(np.interp(coverage, levels, [table[level] for level in levels]))


def _isotonic(probabilities: np.ndarray, outcomes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pool-adjacent-violators isotonic fit, returning ``(thresholds, values)``.

    Implemented here rather than imported so the calibration map is a pair of arrays that
    can be serialised with the model and inspected in a review, instead of a pickled
    estimator whose behaviour nobody can read. The algorithm is exact and O(n).

    ``thresholds`` are the *left* edges of the fitted blocks and are strictly increasing;
    ``values`` are the block means and are non-decreasing. :func:`_apply_isotonic` reads
    them with ``searchsorted(..., "right") - 1``, so the pair is only meaningful under that
    convention: a threshold that is a block's right edge instead of its left shifts every
    boundary by one block and silently mis-calibrates the scores nearest each step.

    Ties are averaged before the fit rather than after. A gradient-boosted model emits the
    same probability for every row that falls in the same leaf, so equal scores are the rule
    here and not an edge case. Pool-adjacent-violators applied to raw ties can place equal
    scores in different blocks and hand them different calibrated values, which makes the
    map depend on the order the frame happened to arrive in - and makes two runs on the same
    data disagree about an individual HCP.
    """
    if probabilities.size == 0:
        return np.empty(0), np.empty(0)

    order = np.argsort(probabilities, kind="mergesort")
    x = probabilities[order].astype(float)
    y = outcomes[order].astype(float)

    # Collapse to one observation per distinct score, carrying its weight.
    unique, first = np.unique(x, return_index=True)
    grouped_sums = np.add.reduceat(y, first)
    grouped_counts = np.diff(np.append(first, y.size)).astype(float)

    # Each block holds (left edge, sum, count); merge backwards whenever the running means
    # stop being non-decreasing. The pops below use explicit temporaries because
    # ``sums[-2] += sums.pop()`` evaluates the negative index *after* the pop has shortened
    # the list, which raises IndexError at exactly two blocks - the most common case there
    # is.
    edges: list[float] = []
    sums: list[float] = []
    counts: list[float] = []
    for edge, block_sum, block_count in zip(unique, grouped_sums, grouped_counts, strict=True):
        edges.append(float(edge))
        sums.append(float(block_sum))
        counts.append(float(block_count))
        while len(sums) > 1 and sums[-2] / counts[-2] > sums[-1] / counts[-1]:
            merged_sum = sums.pop() + sums[-1]
            merged_count = counts.pop() + counts[-1]
            sums[-1] = merged_sum
            counts[-1] = merged_count
            # The merged block starts where the earlier one did, so the later edge goes.
            edges.pop()

    return np.asarray(edges), np.asarray([s / c for s, c in zip(sums, counts, strict=True)])


def _apply_isotonic(
    probabilities: np.ndarray, thresholds: np.ndarray, values: np.ndarray
) -> np.ndarray:
    if thresholds.size == 0:
        return probabilities
    index = np.searchsorted(thresholds, probabilities, side="right") - 1
    index = np.clip(index, 0, values.size - 1)
    return np.clip(values[index], 0.0, 1.0)


class AttendanceForecaster:
    """Both sub-models, fitted and validated together.

    One class because they answer one planner question at two levels of detail and must
    not disagree: the event-level model's implied rate is checked against the
    per-invitation model's mean probability at fit time, and a material divergence is
    surfaced as a warning rather than left for someone to discover in a meeting.
    """

    def __init__(self, spec: AttendanceModelSpec | None = None) -> None:
        self.spec = spec or AttendanceModelSpec()
        self._invitation_model = None
        self._event_model = None
        self._calibration: tuple[np.ndarray, np.ndarray] | None = None
        self.historical_rate = float("nan")
        self.residual_sd = float("nan")
        self.event_residual_sd = float("nan")
        self.observed_ranges: dict[str, tuple[float, float]] = {}
        #: Fitted range of each event-grain feature. Kept separately from
        #: :attr:`observed_ranges` because the two frames share feature names
        #: (``days_notice``, ``is_virtual``) whose ranges are not the same object: one is
        #: measured over invitations, the other over events, and a design must be checked
        #: against the second.
        self.event_ranges: dict[str, tuple[float, float]] = {}
        #: Standard deviation of ``(actual - expected) / expected`` across holdout events.
        #: See :meth:`_summed_residual_sd` for why the *relative* figure is the one that
        #: transfers to a room of a different size.
        self.relative_residual_sd = float("nan")
        self.event_relative_residual_sd = float("nan")
        self.n_invitations = 0
        self.n_events = 0
        self.fitted = False

    # -- fitting ------------------------------------------------------------
    def fit(self, invitations: pd.DataFrame, events: pd.DataFrame) -> AttendanceForecaster:
        """Fit both sub-models.

        ``invitations`` needs :data:`INVITATION_FEATURES` plus ``event_id``,
        ``event_month_index`` and a boolean ``attended``. ``events`` needs
        :data:`EVENT_FEATURES` plus ``event_id``, ``event_month_index`` and
        ``verified_attendees``. Missing feature columns are filled with zero and named in
        a warning rather than raising, because a tenant that has never recorded travel
        distance should get a model without it instead of no model.
        """
        import lightgbm as lgb

        warnings: list[str] = []
        inv = invitations.sort_values("event_month_index").reset_index(drop=True)
        evt = events.sort_values("event_month_index").reset_index(drop=True)
        self.n_invitations, self.n_events = len(inv), len(evt)

        inv_x, missing_inv = self._matrix(inv, INVITATION_FEATURES)
        evt_x, missing_evt = self._matrix(evt, EVENT_FEATURES)
        for name in sorted(set(missing_inv) | set(missing_evt)):
            warnings.append(f"feature {name} was absent and treated as zero for every row")

        attended = inv["attended"].astype(bool).to_numpy()
        self.historical_rate = float(attended.mean()) if attended.size else float("nan")
        for column in INVITATION_FEATURES:
            if column in inv:
                series = pd.to_numeric(inv[column], errors="coerce").dropna()
                if not series.empty:
                    self.observed_ranges[column] = (float(series.min()), float(series.max()))
        for column in EVENT_FEATURES:
            if column in evt.columns:
                series = pd.to_numeric(evt[column], errors="coerce").dropna()
                if not series.empty:
                    self.event_ranges[column] = (float(series.min()), float(series.max()))

        if self.n_invitations >= MIN_INVITATIONS:
            n_hold = max(1, round(self.n_invitations * self.spec.holdout_share))
            head = slice(0, self.n_invitations - n_hold)
            tail = slice(self.n_invitations - n_hold, self.n_invitations)
            self._invitation_model = lgb.LGBMClassifier(
                objective="binary",
                learning_rate=self.spec.learning_rate,
                num_leaves=self.spec.num_leaves,
                min_child_samples=self.spec.min_data_in_leaf,
                n_estimators=self.spec.n_estimators,
                random_state=self.spec.random_state,
                verbose=-1,
            ).fit(inv_x[head], attended[head])
            raw = self._invitation_model.predict_proba(inv_x[tail])[:, 1]
            if self.spec.calibrate and raw.size >= 50:
                self._calibration = _isotonic(raw, attended[tail].astype(float))
            calibrated = self._predict_invitation(inv_x[tail])
            # The interval on a summed forecast comes from the dispersion of realised
            # event-level totals around their predicted totals, not from the per-row
            # variance: independent Bernoulli draws would imply an interval far narrower
            # than reality, because whether a room fills is dominated by shared shocks -
            # weather, a competing congress, a speaker cancelling - that no per-invitation
            # feature captures.
            self.residual_sd, self.relative_residual_sd = self._summed_residual_sd(
                inv.iloc[tail], calibrated
            )
        else:
            warnings.append(
                f"only {self.n_invitations} invitations are available (a per-invitation "
                f"model needs about {MIN_INVITATIONS}), so reach is forecast from the "
                f"historical attendance rate of {self.historical_rate:.0%}"
            )

        if self.n_events >= MIN_EVENTS_FOR_EVENT_MODEL:
            n_hold = max(1, round(self.n_events * self.spec.holdout_share))
            head = slice(0, self.n_events - n_hold)
            tail = slice(self.n_events - n_hold, self.n_events)
            target = pd.to_numeric(evt["verified_attendees"], errors="coerce").fillna(0.0)
            self._event_model = lgb.LGBMRegressor(
                objective="tweedie",
                tweedie_variance_power=self.spec.tweedie_power,
                learning_rate=self.spec.learning_rate,
                num_leaves=self.spec.num_leaves,
                min_child_samples=max(5, self.spec.min_data_in_leaf // 4),
                n_estimators=self.spec.n_estimators,
                random_state=self.spec.random_state,
                verbose=-1,
            ).fit(evt_x[head], target.to_numpy()[head])
            predicted = np.maximum(self._event_model.predict(evt_x[tail]), 0.0)
            residuals = target.to_numpy()[tail] - predicted
            self.event_residual_sd = (
                float(np.std(residuals, ddof=1)) if residuals.size > 1 else float("nan")
            )
            safe = np.maximum(predicted, 1.0)
            self.event_relative_residual_sd = (
                float(np.std(residuals / safe, ddof=1)) if residuals.size > 1 else float("nan")
            )
        else:
            warnings.append(
                f"only {self.n_events} events are available (a design-level model needs about "
                f"{MIN_EVENTS_FOR_EVENT_MODEL}), so attendance for a proposed design is "
                "forecast as the historical rate times the planned invitation count"
            )

        self.fitted = True
        self.warnings = tuple(warnings)
        _LOG.info(
            "forecast.attendance.fitted",
            spec=self.spec.fingerprint,
            n_invitations=self.n_invitations,
            n_events=self.n_events,
            historical_rate=self.historical_rate,
            invitation_model=self._invitation_model is not None,
            event_model=self._event_model is not None,
            calibrated=self._calibration is not None,
        )
        return self

    @staticmethod
    def _matrix(frame: pd.DataFrame, columns: tuple[str, ...]) -> tuple[np.ndarray, list[str]]:
        missing = [c for c in columns if c not in frame.columns]
        data = {
            c: (
                pd.to_numeric(frame[c], errors="coerce").fillna(0.0)
                if c in frame.columns
                else pd.Series(0.0, index=frame.index)
            )
            for c in columns
        }
        return pd.DataFrame(data, index=frame.index).to_numpy(dtype=float), missing

    def _predict_invitation(self, matrix: np.ndarray) -> np.ndarray:
        if self._invitation_model is None:
            return np.full(matrix.shape[0], self.historical_rate, dtype=float)
        raw = self._invitation_model.predict_proba(matrix)[:, 1]
        if self._calibration is None:
            return raw
        return _apply_isotonic(raw, *self._calibration)

    def _summed_residual_sd(
        self, holdout: pd.DataFrame, probabilities: np.ndarray
    ) -> tuple[float, float]:
        """Dispersion of realised attendance around its forecast, absolute and relative.

        Both are measured across whole holdout *events*, never across invitations. Treating
        invitations as independent Bernoulli draws gives a standard deviation of about two
        percent on a thousand-person forecast, which is spectacularly overconfident: whether
        a room fills is dominated by shocks no per-invitation feature captures - weather, a
        competing congress, a rep who did not make their calls - and those shocks land on
        every invitee at once.

        The *relative* figure is what a forecast for a different-sized room needs. Shared
        shocks act on the attendance rate, so their effect on the headcount scales with the
        room: an absolute standard deviation measured on 40-person programs under-covers a
        400-person one by an order of magnitude and over-covers a 10-person one just as
        badly. The absolute figure is kept as a floor for the degenerate case where every
        training event was the same size and the relative estimate is therefore unmeasurable.
        """
        frame = holdout.assign(_p=probabilities)
        grouped = frame.groupby("event_id").agg(
            expected=("_p", "sum"), actual=("attended", lambda s: float(s.astype(bool).sum()))
        )
        if len(grouped) < 2:
            return float("nan"), float("nan")
        residuals = grouped["actual"] - grouped["expected"]
        absolute = float(residuals.std(ddof=1))
        relative = float((residuals / grouped["expected"].clip(lower=1.0)).std(ddof=1))
        return absolute, relative

    def _dispersion(
        self, expected: float, relative_sd: float, absolute_sd: float, binomial_var: float
    ) -> tuple[float, str]:
        """Combine proportional dispersion with the irreducible sampling floor.

        Returns ``(sd, caveat)`` where an empty caveat means the estimate came from measured
        event-to-event variation. The two terms are added in variance because they are
        different things: the proportional term is the shared shock, the binomial term is
        the coin-flip residual that survives even if every shock were known. Reporting only
        the larger of the two would understate a forecast where both matter.
        """
        if np.isfinite(relative_sd) and relative_sd > 0.0:
            shock = relative_sd * max(expected, 0.0)
            return float(math.sqrt(shock**2 + max(binomial_var, 0.0))), ""
        if np.isfinite(absolute_sd) and absolute_sd > 0.0:
            return float(math.sqrt(absolute_sd**2 + max(binomial_var, 0.0))), (
                "the interval was scaled from an absolute dispersion measured on past "
                "programs because their sizes did not vary enough to measure a "
                "proportional one; it is most trustworthy for a program of similar size"
            )
        return float(math.sqrt(max(binomial_var, 0.0))), (
            "the interval is a binomial approximation because too few past events were "
            "available to measure how far realised attendance drifts from its forecast; "
            "treat it as a lower bound on the true uncertainty"
        )

    # -- prediction ---------------------------------------------------------
    def forecast_reach(
        self,
        invitations: pd.DataFrame,
        *,
        segment_column: str | None = None,
    ) -> ReachForecast:
        """Expected verified attendance for a concrete invitation list."""
        if not self.fitted:
            raise RuntimeError("forecast_reach() called before fit()")
        if invitations.empty:
            return ReachForecast(
                mode=ForecastMode.OUT_OF_SUPPORT,
                expected_attendees=float("nan"),
                low=float("nan"),
                high=float("nan"),
                coverage=self.spec.coverage,
                n_invitations=0,
                out_of_support=("invitations",),
                remedy="an invitation list is required to forecast reach",
                spec_fingerprint=self.spec.fingerprint,
            )

        matrix, missing = self._matrix(invitations, INVITATION_FEATURES)
        probabilities = self._predict_invitation(matrix)
        expected = float(probabilities.sum())
        warnings = list(getattr(self, "warnings", ()))
        for name in missing:
            warnings.append(f"feature {name} was absent from the request and treated as zero")

        # Out-of-range features widen nothing and refuse nothing on their own - a single
        # unusually distant invitee is not grounds to refuse a 200-person forecast - but a
        # list whose *majority* sits outside the fitted range is a different population.
        drifted = self._drifted_features(invitations)
        if drifted:
            warnings.append(
                "most invitations fall outside the range this model was fitted on for: "
                + ", ".join(drifted)
                + "; the forecast is reported but its calibration is not established here"
            )

        mode = ForecastMode.MODEL if self._invitation_model is not None else ForecastMode.POOLED
        binomial_var = float(np.sum(probabilities * (1.0 - probabilities)))
        sd, caveat = self._dispersion(
            expected, self.relative_residual_sd, self.residual_sd, binomial_var
        )
        if caveat:
            warnings.append(caveat)
        half = _z_for(self.spec.coverage) * sd

        by_segment = pd.DataFrame()
        if segment_column and segment_column in invitations.columns:
            by_segment = (
                invitations.assign(_p=probabilities)
                .groupby(segment_column, as_index=False)
                .agg(invitations=("_p", "size"), expected_attendees=("_p", "sum"))
            )
            by_segment["share"] = by_segment["expected_attendees"] / max(expected, 1e-9)
        elif segment_column:
            warnings.append(
                f"segment column {segment_column} is not present, so no composition "
                "forecast was produced"
            )

        return ReachForecast(
            mode=mode,
            expected_attendees=expected,
            low=max(0.0, expected - half),
            high=min(float(len(invitations)), expected + half),
            coverage=self.spec.coverage,
            n_invitations=len(invitations),
            by_segment=by_segment,
            mean_probability=float(probabilities.mean()),
            spec_fingerprint=self.spec.fingerprint,
            warnings=tuple(warnings),
        )

    def _drifted_features(self, frame: pd.DataFrame) -> list[str]:
        drifted: list[str] = []
        for column, (low, high) in self.observed_ranges.items():
            if column not in frame.columns:
                continue
            series = pd.to_numeric(frame[column], errors="coerce").dropna()
            if series.empty:
                continue
            outside = float(((series < low) | (series > high)).mean())
            if outside > 0.5:
                drifted.append(f"{column} ({outside:.0%} outside {low:g}-{high:g})")
        return drifted

    def forecast_design(self, design: dict[str, float]) -> AttendanceForecast:
        """Expected verified attendance for a proposed design with no invitation list.

        ``design`` carries :data:`EVENT_FEATURES`. Refuses when ``invitations_planned`` is
        absent or non-positive: every fallback path and the implied-rate diagnostic depend
        on it, and inventing one would make the answer arbitrary.
        """
        if not self.fitted:
            raise RuntimeError("forecast_design() called before fit()")
        planned = float(design.get("invitations_planned", 0.0) or 0.0)
        if not np.isfinite(planned) or planned <= 0:
            return AttendanceForecast(
                mode=ForecastMode.OUT_OF_SUPPORT,
                expected_attendees=float("nan"),
                low=float("nan"),
                high=float("nan"),
                coverage=self.spec.coverage,
                implied_rate=float("nan"),
                out_of_support=("invitations_planned",),
                remedy="a positive planned invitation count is required",
                spec_fingerprint=self.spec.fingerprint,
            )

        warnings = list(getattr(self, "warnings", ()))
        frame = pd.DataFrame([{c: float(design.get(c, 0.0) or 0.0) for c in EVENT_FEATURES}])
        matrix, _ = self._matrix(frame, EVENT_FEATURES)

        # A design outside the fitted range is where a boosted tree is at its most
        # dangerous: it does not extrapolate, it *saturates*, returning the mean of its
        # highest leaf. Asked about 4,000 invitations after being fitted on 20-120, it
        # confidently answers with the attendance of a 120-person program. The historical
        # rate does extrapolate - badly, but monotonically and visibly - so out-of-range
        # designs are answered from the rate and told so. This is the M3/M4 asymmetry
        # applied within M4: extrapolating a turnout rate degrades gracefully, which is
        # why this warns where the impact forecaster refuses.
        extrapolating = [
            f"{column} ({value:g} outside {low:g}-{high:g})"
            for column, (low, high) in self.event_ranges.items()
            if not (low <= (value := float(design.get(column, 0.0) or 0.0)) <= high)
        ]

        if self._event_model is not None and not extrapolating:
            expected = float(max(self._event_model.predict(matrix)[0], 0.0))
            mode = ForecastMode.MODEL
            relative_sd = self.event_relative_residual_sd
            absolute_sd = self.event_residual_sd
        else:
            if extrapolating and self._event_model is not None:
                warnings.append(
                    "this design falls outside the range of every measured program for: "
                    + ", ".join(extrapolating)
                    + "; attendance was forecast from the historical attendance rate of "
                    f"{self.historical_rate:.0%} instead of from the design model, which "
                    "cannot extrapolate beyond what it has seen"
                )
            expected = planned * self.historical_rate
            mode = ForecastMode.POOLED
            relative_sd = self.event_relative_residual_sd
            absolute_sd = float("nan")

        rate = self.historical_rate if np.isfinite(self.historical_rate) else 0.3
        binomial_var = max(planned * rate * (1.0 - rate), 0.0)
        sd, caveat = self._dispersion(expected, relative_sd, absolute_sd, binomial_var)
        if caveat:
            warnings.append(caveat)
        half = _z_for(self.spec.coverage) * sd

        capacity = float(design.get("venue_capacity", 0.0) or 0.0)
        ceiling = min(planned, capacity) if capacity > 0 else planned
        if expected > ceiling:
            warnings.append(
                f"the model predicts {expected:.0f} attendees against a ceiling of "
                f"{ceiling:.0f} (planned invitations and venue capacity); the forecast was "
                "capped, which usually means the design is outside anything measured"
            )
            expected = ceiling

        return AttendanceForecast(
            mode=mode,
            expected_attendees=expected,
            low=max(0.0, expected - half),
            high=min(ceiling, expected + half),
            coverage=self.spec.coverage,
            implied_rate=expected / planned,
            spec_fingerprint=self.spec.fingerprint,
            warnings=tuple(warnings),
        )

    def score_invitations(self, invitations: pd.DataFrame) -> pd.DataFrame:
        """Per-invitation attendance probabilities. **Logistics use only.**

        Returned as ``(event_id, hcp_id, attendance_probability)`` and nothing else. Any
        join that attaches a prescribing metric to this frame builds the named-HCP
        prescribing ranking plan.md §15 forbids for attendee or speaker selection; the
        narrow return type is here so that such a join has to be written on purpose.
        """
        if not self.fitted:
            raise RuntimeError("score_invitations() called before fit()")
        matrix, _ = self._matrix(invitations, INVITATION_FEATURES)
        out = invitations[[c for c in ("event_id", "hcp_id") if c in invitations.columns]].copy()
        out["attendance_probability"] = self._predict_invitation(matrix)
        return out

    # -- validation ---------------------------------------------------------
    def validate(self, invitations: pd.DataFrame, events: pd.DataFrame) -> ReachValidation:
        """Temporal holdout by event, scoring discrimination, calibration and headcount.

        The split is on ``event_month_index`` at the event grain and then applied to
        invitations by ``event_id``, so no event contributes rows to both sides. Splitting
        invitations directly would let a model learn one event's idiosyncratic turnout
        from half its own invitation list and then predict the other half.
        """
        inv = invitations.sort_values("event_month_index").reset_index(drop=True)
        evt = events.sort_values("event_month_index").reset_index(drop=True)
        n_hold = max(1, round(len(evt) * self.spec.holdout_share))
        holdout_ids = set(evt.iloc[len(evt) - n_hold :]["event_id"])
        train_inv = inv[~inv["event_id"].isin(holdout_ids)]
        hold_inv = inv[inv["event_id"].isin(holdout_ids)]
        warnings: list[str] = []
        if train_inv.empty or hold_inv.empty:
            return ReachValidation(
                n_train_invitations=len(train_inv),
                n_holdout_invitations=len(hold_inv),
                auc=float("nan"),
                calibration_slope=float("nan"),
                brier=float("nan"),
                baseline_brier=float("nan"),
                event_mae=float("nan"),
                baseline_event_mae=float("nan"),
                interval_coverage=float("nan"),
                warnings=("the temporal split left one side empty; nothing was scored",),
            )

        inner = AttendanceForecaster(self.spec).fit(
            train_inv, evt[~evt["event_id"].isin(holdout_ids)]
        )
        matrix, _ = self._matrix(hold_inv, INVITATION_FEATURES)
        probabilities = inner._predict_invitation(matrix)
        actual = hold_inv["attended"].astype(bool).to_numpy()

        auc = _auc(probabilities, actual)
        brier = float(np.mean((probabilities - actual.astype(float)) ** 2))
        base_rate = inner.historical_rate
        baseline_brier = float(np.mean((base_rate - actual.astype(float)) ** 2))
        slope, calib_warning = _calibration_slope(probabilities, actual)
        if calib_warning:
            warnings.append(calib_warning)

        scored = hold_inv.assign(_p=probabilities)
        grouped = scored.groupby("event_id").agg(
            expected=("_p", "sum"),
            actual=("attended", lambda s: float(s.astype(bool).sum())),
            n=("_p", "size"),
        )
        grouped["baseline"] = grouped["n"] * base_rate
        event_mae = float((grouped["actual"] - grouped["expected"]).abs().mean())
        baseline_mae = float((grouped["actual"] - grouped["baseline"]).abs().mean())

        sd = inner.residual_sd
        if np.isfinite(sd) and sd > 0:
            half = 1.2816 * sd
            covered = (grouped["actual"] >= grouped["expected"] - half) & (
                grouped["actual"] <= grouped["expected"] + half
            )
            coverage = float(covered.mean())
        else:
            coverage = float("nan")
            warnings.append("no calibrated interval was available, so coverage was not measured")

        by_segment = pd.DataFrame()
        if "specialty_rank" in hold_inv.columns:
            by_segment = (
                scored.assign(error=scored["_p"] - actual.astype(float))
                .groupby("specialty_rank", as_index=False)
                .agg(n=("_p", "size"), mean_error=("error", "mean"))
            )

        report = ReachValidation(
            n_train_invitations=len(train_inv),
            n_holdout_invitations=len(hold_inv),
            auc=auc,
            calibration_slope=slope,
            brier=brier,
            baseline_brier=baseline_brier,
            event_mae=event_mae,
            baseline_event_mae=baseline_mae,
            interval_coverage=coverage,
            by_segment=by_segment,
            warnings=tuple(warnings),
        )
        _LOG.info(
            "forecast.attendance.validated",
            spec=self.spec.fingerprint,
            auc=auc,
            brier=brier,
            baseline_brier=baseline_brier,
            calibration_slope=slope,
            event_mae=event_mae,
            baseline_event_mae=baseline_mae,
            interval_coverage=coverage,
            beats_baseline=report.beats_baseline,
        )
        return report


def _auc(scores: np.ndarray, outcomes: np.ndarray) -> float:
    """Rank-based AUC with correct tie handling.

    Computed from the Mann-Whitney statistic on average ranks rather than by sweeping a
    threshold, so that a model emitting many identical probabilities - which a shallow
    tree does - scores 0.5 on those ties instead of whatever the sort order happened to be.
    """
    positive = int(outcomes.sum())
    negative = int(outcomes.size - positive)
    if positive == 0 or negative == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(scores.size, dtype=float)
    sorted_scores = scores[order]
    i = 0
    while i < sorted_scores.size:
        j = i
        while j + 1 < sorted_scores.size and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    positive_ranks = ranks[outcomes.astype(bool)].sum()
    return float((positive_ranks - positive * (positive + 1) / 2.0) / (positive * negative))


def _calibration_slope(scores: np.ndarray, outcomes: np.ndarray) -> tuple[float, str]:
    """Slope of observed rate on predicted rate across probability deciles.

    Deciles rather than a logistic recalibration fit because the deciles are what the
    model card plots, and a slope computed on a different decomposition than the one a
    reviewer sees invites an argument nobody can settle.
    """
    if scores.size < 20:
        return float("nan"), "too few holdout invitations to measure calibration"
    try:
        bins = pd.qcut(scores, 10, duplicates="drop", labels=False)
    except ValueError:
        return float("nan"), "predicted probabilities are too concentrated to bin"
    frame = pd.DataFrame({"bin": bins, "p": scores, "y": outcomes.astype(float)})
    grouped = frame.groupby("bin").agg(p=("p", "mean"), y=("y", "mean"))
    if len(grouped) < 3:
        return float("nan"), "predicted probabilities occupy fewer than three deciles"
    x = grouped["p"].to_numpy()
    y = grouped["y"].to_numpy()
    variance = float(((x - x.mean()) ** 2).sum())
    if variance <= 0:
        return float("nan"), "predicted probabilities have no spread"
    return float(((x - x.mean()) * (y - y.mean())).sum() / variance), ""
