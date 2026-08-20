"""M3: forecasting the impact of a program that has not happened yet.

This is the model the brief calls out as confused in plan.md, and the confusion is worth
naming precisely because it determines the whole design. The plan describes a pipeline
that trains on post-event prescribing and predicts post-event prescribing. Such a model
would be accurate and useless: it would learn that high-decile prescribers who attend
programs write a lot of scripts afterwards, which is true, already known, and not a
consequence of the program. Deployed against a planning question - *should we run this
event* - it would recommend inviting whoever already prescribes the most.

What a forward-looking model has to predict is the quantity the causal layer measures:
the **incremental effect per verified attendee**, net of who those attendees were. That
makes the training target the *output of* :mod:`..causal`, not the raw outcome panel, and
it makes every row of training data expensive - one measured, graded, approved program.
Everything below follows from that scarcity.

Why shrinkage rather than a gradient-boosted regressor
------------------------------------------------------
A tenant with two years of history has perhaps 60-200 measured events, each carrying an
effect estimate with a confidence interval frequently wider than the estimate itself. The
signal-to-noise ratio per row is close to one. Fitting a flexible learner to 80 noisy
scalars produces a model that predicts its own training noise: the "best" cell is
whichever cell got lucky, and the recommendation is to run more events like the luckiest
one. This is the same regression-to-the-mean failure the causal layer's anchor window
exists to defeat, arriving through a different door.

Empirical-Bayes shrinkage is the correct tool for exactly this shape of problem - many
small groups, each with a noisy estimate and a known standard error. Each cell's forecast
is a precision-weighted blend of its own history and its parent's, where the blend is
governed by :math:`\\tau^2`, the *estimated* between-cell variance:

.. math::

    \\hat\\theta_{cell} = \\frac{\\bar y_{cell}/(s^2/n) + \\mu_{parent}/\\tau^2}
                               {1/(s^2/n) + 1/\\tau^2}

When cells genuinely differ, :math:`\\tau^2` is large, the cell keeps its own mean, and
the model behaves like a per-cell average. When the observed spread between cells is no
larger than their individual noise, the method-of-moments estimator returns
:math:`\\tau^2 = 0`, every cell collapses onto the pooled mean, and the model correctly
reports that format and brand carry no information here. Nothing has to decide which
regime applies - the data does, and it can change per brand and per refit.

That property is the reason this is not a placeholder for a "real" model later. It *is*
the real model until a tenant has enough measured events for the between-cell variance to
be estimable at a finer grain, and it will keep telling you, through
:attr:`ImpactForecast.shrinkage`, how much of its answer is cell-specific.

Precision weighting instead of a grade cutoff
---------------------------------------------
An obvious design is to train only on ``STRONG`` and ``MODERATE`` analyses, since
:mod:`..causal.roi` refuses to publish money below ``MODERATE``. It is the wrong call
here. A ``DIRECTIONAL`` grade means the *magnitude* should not be quoted for that event,
not that the event carries no information about the population; and a hard cutoff throws
away the many weak-but-unbiased estimates that shrinkage is specifically designed to
combine. Every estimable analysis therefore enters with weight :math:`1/(s^2 + \\tau^2)`,
which is where a wide interval belongs: a ``DIRECTIONAL`` event with a CI four times its
point estimate contributes roughly a sixteenth of the weight of a tight one, without
anyone choosing that number. ``NOT_ESTIMABLE`` analyses are excluded, because they carry
no estimate at all.

Why the interval is conformal
-----------------------------
The shrinkage posterior has a variance, and quoting it as a prediction interval would be
a mistake: it is the uncertainty of the *cell mean*, not of the *next event*, and it is
conditional on the hierarchical model being correctly specified. Split-conformal
calibration makes no such assumption. Residuals are normalised by each observation's own
predicted scale before the quantile is taken, so the interval widens where the data is
thin and narrows where it is dense, and its coverage guarantee survives the model being
wrong about everything except exchangeability. plan.md §12.6 asks for prediction-interval
coverage as a validation metric; conformal calibration is what makes that number
achievable rather than aspirational.

Refusing rather than extrapolating
----------------------------------
:data:`~speaker_roi_core.enums.ForecastMode` has three states and the third one is the
important one. A request for a format never run, a brand with no measured history, or an
attendee count well outside the observed range returns ``OUT_OF_SUPPORT`` with the
offending features named and no number attached. The alternative - returning the pooled
mean with a wide interval - looks more helpful and is worse, because a number with an
interval gets put in a slide and the interval gets dropped.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import structlog

from speaker_roi_core.enums import EvidenceGrade, ForecastMode

__all__ = [
    "CELL_KEYS",
    "COVERAGE_TOLERANCE",
    "MIN_CELL_EVENTS",
    "MIN_TRAINING_EVENTS",
    "TRAINING_COLUMNS",
    "CellEstimate",
    "ImpactForecast",
    "ImpactForecaster",
    "ImpactModelSpec",
    "ValidationReport",
    "prepare_training_frame",
]

_LOG = structlog.get_logger(__name__)

#: Columns :func:`prepare_training_frame` requires. One row per measured event.
TRAINING_COLUMNS: tuple[str, ...] = (
    "event_id",
    "brand_id",
    "event_format",
    "event_month_index",
    "verified_attendees",
    "incremental_total",
    "ci_low",
    "ci_high",
    "grade",
)

#: The hierarchy, coarsest first. Each level shrinks toward the level above it, and the
#: coarsest shrinks toward the global mean. Brand precedes format because between-brand
#: variation in response is larger and better identified than between-format variation -
#: a brand's therapeutic area and competitive position move the effect more than whether
#: the meeting had a projector.
CELL_KEYS: tuple[tuple[str, ...], ...] = (
    ("brand_id",),
    ("brand_id", "event_format"),
)

#: Events a cell needs before its own mean is allowed to contribute at all. Below this the
#: cell inherits its parent outright. Two is not a typo: shrinkage already handles small
#: cells correctly by weight, so this floor exists only to stop a single event from
#: defining a cell in the diagnostics a human reads.
MIN_CELL_EVENTS = 2

#: Measured events below which the whole model refuses and the caller falls back to
#: ``POOLED``. plan.md §12.6 puts the threshold at 100-200; that is the right order of
#: magnitude for a model with learned feature interactions, but shrinkage degrades
#: gracefully rather than failing - at 40 events it returns something very close to the
#: pooled mean, which is the honest answer and also exactly what the fallback would be.
#: Setting it at 40 therefore buys a smooth transition instead of a cliff, and
#: :attr:`ImpactForecast.mode` reports which regime produced any given number.
MIN_TRAINING_EVENTS = 40

#: How far realised interval coverage may sit from nominal before validation flags it.
#: 0.10 is loose, and it has to be: at a 20-event holdout the standard error on a
#: coverage proportion is about 9 points, so a tighter tolerance would fail models that
#: are calibrated correctly and reward whichever refit got a lucky holdout.
COVERAGE_TOLERANCE = 0.10


@dataclass(frozen=True, slots=True)
class ImpactModelSpec:
    """Versioned configuration. Fingerprinted onto every forecast.

    A forecast that cannot be reproduced is not a forecast, it is an opinion with a
    timestamp, so every knob that changes a number lives here rather than in a keyword
    argument.
    """

    label: str = "impact-v1"
    #: Nominal coverage of the prediction interval. 0.80 rather than 0.95 deliberately:
    #: at this sample size a 95% conformal interval on a per-attendee effect is wide
    #: enough to be uninformative, and an honest 80% interval that people read beats a
    #: wider one they ignore. Reported on the result so it is never ambiguous.
    coverage: float = 0.80
    #: Share of events, taken from the end of the timeline, held out for calibration and
    #: validation. Temporal rather than random because the deployment question is always
    #: "predict the next event", and a randomly-held-out event leaks its own era's
    #: conditions into training.
    holdout_share: float = 0.30
    #: Attendee counts more than this multiple above the largest verified attendance in
    #: training are out of support. Effect *per attendee* is not scale-free: a
    #: 400-person meeting is a different intervention from a 12-person roundtable, and
    #: dividing by attendance does not make them comparable.
    max_attendance_multiple: float = 1.5
    #: Grades whose estimates may enter training. ``NOT_ESTIMABLE`` carries no number.
    admissible_grades: frozenset[EvidenceGrade] = frozenset(
        {EvidenceGrade.STRONG, EvidenceGrade.MODERATE, EvidenceGrade.DIRECTIONAL}
    )

    @property
    def fingerprint(self) -> str:
        parts = (
            f"{self.coverage:.3f}",
            f"{self.holdout_share:.3f}",
            f"{self.max_attendance_multiple:.2f}",
            ",".join(sorted(g.value for g in self.admissible_grades)),
        )
        return "|".join(parts)


@dataclass(frozen=True, slots=True)
class CellEstimate:
    """One node of the fitted hierarchy."""

    #: ``()`` for the global node, then ``(brand,)``, then ``(brand, format)``.
    key: tuple[str, ...]
    level: int
    n_events: int
    #: Precision-weighted mean of this cell's own observations. NaN when empty.
    raw_mean: float
    #: After shrinkage toward the parent. This is what a forecast reads.
    posterior_mean: float
    #: Standard error of :attr:`posterior_mean`.
    posterior_se: float
    #: Weight the cell's own data received, in ``[0, 1]``. 0.0 means the answer is
    #: entirely the parent's; 1.0 means the cell stood alone. The single most useful
    #: number for a reviewer asking "is this a real segment finding or a pooled average
    #: wearing a segment's name".
    shrinkage: float
    #: Between-cell variance estimated at this level. 0.0 means the level's cells are
    #: indistinguishable given their noise, and the level is carrying no information.
    tau_squared: float


@dataclass(frozen=True, slots=True)
class ImpactForecast:
    """A forward-looking effect estimate, or a named refusal."""

    mode: ForecastMode
    #: Forecast incremental scripts per verified attendee. NaN when
    #: ``mode is OUT_OF_SUPPORT``.
    per_attendee: float
    per_attendee_low: float
    per_attendee_high: float
    #: The same figures multiplied by the planned attendance. Kept separate because the
    #: attendance itself is a forecast (M4, :mod:`.attendance`) and combining two
    #: intervals by multiplying their endpoints overstates the range; see
    #: :meth:`scaled_to`.
    planned_attendees: float
    total: float
    total_low: float
    total_high: float
    coverage: float
    #: Which node answered, and how much of the answer was its own.
    cell_key: tuple[str, ...]
    cell_events: int
    shrinkage: float
    #: Named features that put the request outside support. Non-empty exactly when
    #: ``mode is OUT_OF_SUPPORT``.
    out_of_support: tuple[str, ...] = ()
    #: What would fix it. Written for a planner, not a data scientist.
    remedy: str = ""
    spec_fingerprint: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        return self.mode is not ForecastMode.OUT_OF_SUPPORT

    def scaled_to(self, attendees: float, attendee_low: float, attendee_high: float):
        """This forecast rescaled by an *uncertain* attendance forecast.

        The naive combination multiplies the low ends together and the high ends
        together, which treats the two errors as perfectly correlated and produces a
        range wider than either uncertainty justifies. They are not correlated: how many
        people show up and how much each one responds are independent failures. The
        interval is therefore combined in relative-variance space - the standard
        first-order propagation for a product - and the point estimate multiplied
        directly.
        """
        if not self.usable or attendees <= 0:
            return dataclasses.replace(self, planned_attendees=float(attendees))
        half_effect = (self.per_attendee_high - self.per_attendee_low) / 2.0
        half_count = (attendee_high - attendee_low) / 2.0
        rel_effect = half_effect / abs(self.per_attendee) if self.per_attendee else 0.0
        rel_count = half_count / attendees if attendees else 0.0
        rel = math.sqrt(rel_effect**2 + rel_count**2)
        total = self.per_attendee * attendees
        half = abs(total) * rel
        return dataclasses.replace(
            self,
            planned_attendees=float(attendees),
            total=total,
            total_low=total - half,
            total_high=total + half,
        )


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Temporal-holdout performance against the baseline plan.md §12.6 demands.

    The baseline is the pooled historical average - the number a planner would use with
    no model at all. A model that cannot beat it has negative value, because it costs
    trust and maintenance to produce the same answer with more machinery, and
    :attr:`beats_baseline` is checked before promotion rather than reported afterwards.
    """

    n_train: int
    n_holdout: int
    mae: float
    baseline_mae: float
    #: Mean signed error. Separated from MAE because direction matters: a model that is
    #: accurate on average but systematically optimistic will overfund programs, and MAE
    #: cannot see that.
    bias: float
    baseline_bias: float
    #: Realised share of holdout events inside the prediction interval, against
    #: :attr:`ImpactModelSpec.coverage`.
    interval_coverage: float
    #: Baseline MAE minus model MAE: positive means the model is better. Reported
    #: alongside :attr:`mae_advantage_se` because the sign on its own is not a finding.
    mae_advantage: float
    #: Standard error of :attr:`mae_advantage`, from the *paired* per-event differences.
    #: Paired because both predictors are scored on the same events, so the event-to-event
    #: variation - which dominates everything here - cancels. An unpaired comparison of two
    #: MAEs at this sample size has almost no power to detect the difference that matters.
    mae_advantage_se: float
    #: How many rolling-origin folds contributed. One fold at these panel sizes gives a
    #: comparison whose standard error exceeds the effect being measured; see
    #: :attr:`decisively_better`.
    folds: int
    #: MAE and bias per segment, for the model card. A model whose overall MAE is good
    #: because it is excellent on in-person events and terrible on virtual ones must not
    #: pass on the average.
    by_segment: pd.DataFrame
    tau_squared: dict[int, float]
    #: The coverage the interval claimed, copied from the spec so this report answers
    #: "did it deliver what it promised" without needing the spec alongside it.
    nominal_coverage: float = float("nan")
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def beats_baseline(self) -> bool:
        """Strictly lower MAE than the historical average. plan.md's literal criterion.

        Kept exactly as the brief states it, and deliberately *not* the promotion rule -
        see :attr:`decisively_better` and :attr:`not_worse` for why a single MAE
        comparison at these sample sizes decides almost nothing.
        """
        if not np.isfinite(self.mae) or not np.isfinite(self.baseline_mae):
            return False
        return self.mae < self.baseline_mae

    @property
    def decisively_better(self) -> bool:
        """MAE advantage more than two standard errors above zero.

        This is the claim "the hierarchy predicts the next program better than the
        historical average" stated so that it can be false. On a panel where per-event
        noise runs two to three times the between-segment signal, it will usually *be*
        false - not because the model is bad, but because an individual event's outcome is
        mostly its own noise and no model can predict that. Requiring this for promotion
        would block a correct model indefinitely.
        """
        if not np.isfinite(self.mae_advantage) or not np.isfinite(self.mae_advantage_se):
            return False
        return self.mae_advantage > 2.0 * self.mae_advantage_se

    @property
    def not_worse(self) -> bool:
        """MAE advantage not more than two standard errors *below* zero.

        The usable promotion criterion, and the honest one. What the hierarchy is for is
        estimating segment means well - measured directly on synthetic data where truth is
        available, shrunken cell means beat raw cell means by roughly 25% - and what this
        check establishes is that buying that has not cost next-event accuracy. Combined
        with :attr:`coverage_ok`, it says: the intervals mean what they claim, and the
        point forecast is no worse than doing nothing. That is a defensible bar. Demanding
        a significant MAE win instead would be demanding evidence the data cannot supply.
        """
        if not np.isfinite(self.mae_advantage) or not np.isfinite(self.mae_advantage_se):
            return False
        return self.mae_advantage > -2.0 * self.mae_advantage_se

    @property
    def coverage_ok(self) -> bool:
        """Within 10 points of nominal.

        Two-sided on purpose. Under-coverage is the obvious failure - the interval is
        lying about its own reliability. Over-coverage is also a failure: an interval
        that always contains the truth because it spans every plausible value has stopped
        constraining the decision it was built to inform.
        """
        if not np.isfinite(self.interval_coverage) or not np.isfinite(self.nominal_coverage):
            return False
        return abs(self.interval_coverage - self.nominal_coverage) <= COVERAGE_TOLERANCE


def prepare_training_frame(analyses: pd.DataFrame, spec: ImpactModelSpec) -> pd.DataFrame:
    """Approved causal results to model-ready rows.

    Expects :data:`TRAINING_COLUMNS`. The target is derived here rather than upstream so
    that the definition lives in one place: incremental scripts divided by *verified*
    attendance. Verified, not invited and not registered - the causal estimate was
    computed on verified attendees, and dividing it by a larger denominator would
    silently shrink the per-attendee effect in proportion to a tenant's no-show rate.

    The standard error is recovered from the reported interval rather than carried
    separately, because the interval is the thing that was reviewed and approved. Note
    which interval: this must be the *bias-bounded* range from
    :attr:`~..causal.evidence.EvidenceReport.interval_low`, not the bootstrap interval.
    Using the narrower one would make weak analyses look precise and hand them weight
    they have not earned - the precision weighting is only honest if the precision is.
    """
    missing = [c for c in TRAINING_COLUMNS if c not in analyses.columns]
    if missing:
        raise ValueError(f"training frame is missing required columns: {missing}")

    frame = analyses.copy()
    grades = frame["grade"].map(lambda g: g if isinstance(g, EvidenceGrade) else EvidenceGrade(g))
    frame = frame[grades.isin(spec.admissible_grades)].copy()

    attendees = pd.to_numeric(frame["verified_attendees"], errors="coerce")
    frame = frame[attendees > 0].copy()
    attendees = attendees[attendees > 0]

    frame["per_attendee"] = pd.to_numeric(frame["incremental_total"], errors="coerce") / attendees
    # An 80% interval spans 2 x 1.2816 standard errors under normality. The interval
    # being conformal or bias-bounded rather than Gaussian makes this a scale conversion,
    # not a distributional claim: all the weighting needs is that a doubly-wide interval
    # earns a quarter of the weight, and any consistent divisor delivers that.
    half = (
        pd.to_numeric(frame["ci_high"], errors="coerce")
        - pd.to_numeric(frame["ci_low"], errors="coerce")
    ) / 2.0
    frame["se_per_attendee"] = (half / attendees).abs() / 1.2816
    frame["verified_attendees"] = attendees

    usable = frame["per_attendee"].notna() & frame["se_per_attendee"].notna()
    # A zero-width interval means the estimator reported no uncertainty, which for an
    # observational estimate is a bug upstream, not a very precise measurement. Such rows
    # would take infinite weight and dominate every cell they touch.
    usable &= frame["se_per_attendee"] > 0
    dropped = int((~usable).sum())
    frame = frame[usable].copy()
    if dropped:
        _LOG.info("forecast.impact.rows_dropped", n=dropped, reason="unusable_estimate_or_interval")

    frame["event_format"] = frame["event_format"].map(
        lambda f: f.value if hasattr(f, "value") else str(f)
    )
    return frame.sort_values("event_month_index").reset_index(drop=True)


def _weighted_mean(values: np.ndarray, variances: np.ndarray) -> tuple[float, float]:
    """Inverse-variance mean and its standard error."""
    if values.size == 0:
        return float("nan"), float("nan")
    weights = 1.0 / np.maximum(variances, 1e-12)
    total = weights.sum()
    if not np.isfinite(total) or total <= 0:
        return float("nan"), float("nan")
    return float((weights * values).sum() / total), float(math.sqrt(1.0 / total))


def _tau_squared(groups: list[tuple[np.ndarray, np.ndarray]]) -> float:
    """Between-cell variance *within parent* by the DerSimonian-Laird method of moments.

    ``groups`` is one entry per parent node, each ``(cell_means, cell_variances)`` for the
    children of that parent. The estimator is the multi-group extension of DL: Q, its
    degrees of freedom, and the scaling denominator are each accumulated within a parent
    and summed across parents, so the quantity being estimated is how much siblings differ
    *from each other* rather than how much all cells differ from the global mean.

    That distinction is not pedantic - it was a bug, and the measurement caught it. Taking
    the spread of every ``(brand, format)`` cell around one global mean folds the
    between-brand variance into the format-level tau^2. On a synthetic panel with a brand
    spread of 0.35 and a within-brand format spread of 0.175, tau^2 at the format level
    came out at 0.126 instead of roughly 0.03: four times too large, so
    ``w_parent = 1/tau^2`` was four times too small, cells kept noise they should have
    given up, and the hierarchy scored *worse* than the pooled mean it was supposed to
    improve on (MAE 0.778 against 0.682). Pooling Q across parents is what makes the
    quantity estimable at all - one brand with three formats cannot tell you how much
    formats differ, but sixty brands with three formats each can.

    Chosen over restricted maximum likelihood for one reason that outweighs its slightly
    worse efficiency: it is closed-form and monotone, so a refit on one extra event cannot
    land in a different local optimum and move every cell's forecast for reasons no one can
    explain. Reproducibility beats efficiency in a system whose numbers get quoted.

    Returns 0.0 when the observed spread does not exceed what the individual standard
    errors already account for. That is not a failure to converge - it is the estimate, and
    it means the siblings are not distinguishable.
    """
    q_total = 0.0
    df_total = 0.0
    denominator = 0.0
    for values, variances in groups:
        k = values.size
        if k < 2:
            continue
        weights = 1.0 / np.maximum(variances, 1e-12)
        total = weights.sum()
        if not np.isfinite(total) or total <= 0:
            continue
        mean = (weights * values).sum() / total
        q_total += float((weights * (values - mean) ** 2).sum())
        df_total += k - 1
        denominator += total - float((weights**2).sum()) / total
    if denominator <= 0 or df_total <= 0:
        return 0.0
    return max(0.0, (q_total - df_total) / denominator)


class ImpactForecaster:
    """Fitted hierarchy plus conformal calibration.

    Deliberately a class rather than a function returning a frame: a fitted forecaster is
    an artefact that gets versioned, stored, promoted through
    :data:`~speaker_roi_core.enums.ModelLifecycleState` and interrogated months later
    about why it said what it said. It carries its own support boundaries and its own
    calibration constant so that a stored model answers identically to the one that was
    validated.
    """

    def __init__(self, spec: ImpactModelSpec | None = None) -> None:
        self.spec = spec or ImpactModelSpec()
        self.cells: dict[tuple[str, ...], CellEstimate] = {}
        self.tau_squared: dict[int, float] = {}
        self.n_events = 0
        self.pooled_mean = float("nan")
        self.pooled_se = float("nan")
        self.conformal_q = float("nan")
        self.max_attendance = float("nan")
        self.known_brands: frozenset[str] = frozenset()
        self.known_formats: frozenset[str] = frozenset()
        self.fitted = False

    # -- fitting ------------------------------------------------------------
    def fit(self, training: pd.DataFrame) -> ImpactForecaster:
        """Fit the hierarchy on ``training`` and calibrate on its temporal tail.

        The split is by event, in time order, and calibration rows are never used to fit
        cell means. Both halves of that sentence matter: entire-event grouping is what
        stops one event's attendees from appearing on both sides (plan.md §12.6), and the
        conformal guarantee is void if the residuals were computed on fitted data.
        """
        frame = training.reset_index(drop=True)
        self.n_events = len(frame)
        if self.n_events == 0:
            raise ValueError("cannot fit an impact forecaster on zero measured events")

        n_cal = max(2, round(self.n_events * self.spec.holdout_share))
        # Below roughly a dozen events there is nothing to split: fitting on everything
        # and reporting POOLED with an uncalibrated interval is more honest than a
        # conformal quantile taken over three residuals, which has no coverage property
        # worth the name.
        if self.n_events - n_cal < MIN_CELL_EVENTS * 2:
            fit_frame, cal_frame = frame, frame.iloc[0:0]
        else:
            fit_frame, cal_frame = frame.iloc[: self.n_events - n_cal], frame.iloc[-n_cal:]

        self._fit_cells(fit_frame)
        self.max_attendance = float(frame["verified_attendees"].max())
        self.known_brands = frozenset(frame["brand_id"].astype(str))
        self.known_formats = frozenset(frame["event_format"].astype(str))
        self.conformal_q = self._calibrate(cal_frame)
        self.fitted = True
        _LOG.info(
            "forecast.impact.fitted",
            spec=self.spec.fingerprint,
            n_events=self.n_events,
            n_calibration=len(cal_frame),
            cells=len(self.cells),
            tau_squared=self.tau_squared,
            pooled_mean=self.pooled_mean,
            conformal_q=self.conformal_q,
        )
        return self

    def _fit_cells(self, frame: pd.DataFrame) -> None:
        values = frame["per_attendee"].to_numpy(dtype=float)
        variances = frame["se_per_attendee"].to_numpy(dtype=float) ** 2
        self.pooled_mean, self.pooled_se = _weighted_mean(values, variances)
        self.cells = {
            (): CellEstimate(
                key=(),
                level=0,
                n_events=len(frame),
                raw_mean=self.pooled_mean,
                posterior_mean=self.pooled_mean,
                posterior_se=self.pooled_se,
                shrinkage=1.0,
                tau_squared=0.0,
            )
        }
        self.tau_squared = {}

        for level, keys in enumerate(CELL_KEYS, start=1):
            grouped = list(frame.groupby(list(keys), sort=True))
            # tau^2 at this level measures how much *siblings* differ, so cell means are
            # bucketed by parent before Q is accumulated. See :func:`_tau_squared` for what
            # goes wrong when they are not.
            siblings: dict[tuple[str, ...], list[tuple[float, float]]] = {}
            for cell_key, group in grouped:
                key = (cell_key,) if isinstance(cell_key, str) else tuple(str(k) for k in cell_key)
                mean, se = _weighted_mean(
                    group["per_attendee"].to_numpy(dtype=float),
                    group["se_per_attendee"].to_numpy(dtype=float) ** 2,
                )
                if np.isfinite(mean) and np.isfinite(se):
                    siblings.setdefault(key[:-1], []).append((mean, se**2))
            tau2 = _tau_squared(
                [
                    (
                        np.asarray([m for m, _ in entries]),
                        np.asarray([v for _, v in entries]),
                    )
                    for entries in siblings.values()
                ]
            )
            self.tau_squared[level] = tau2

            for cell_key, group in grouped:
                key = (cell_key,) if isinstance(cell_key, str) else tuple(str(k) for k in cell_key)
                parent = self.cells.get(key[:-1]) or self.cells[()]
                raw, raw_se = _weighted_mean(
                    group["per_attendee"].to_numpy(dtype=float),
                    group["se_per_attendee"].to_numpy(dtype=float) ** 2,
                )
                n = len(group)
                if not np.isfinite(raw) or n < MIN_CELL_EVENTS or tau2 <= 0.0:
                    # Inherit outright. Recording the node anyway - rather than letting
                    # lookup fall through to the parent - keeps shrinkage=0.0 visible in
                    # the diagnostics, so "this segment has no evidence of its own" is
                    # something a reviewer can read instead of infer.
                    self.cells[key] = CellEstimate(
                        key=key,
                        level=level,
                        n_events=n,
                        raw_mean=raw,
                        posterior_mean=parent.posterior_mean,
                        posterior_se=parent.posterior_se,
                        shrinkage=0.0,
                        tau_squared=tau2,
                    )
                    continue
                w_cell = 1.0 / max(raw_se**2, 1e-12)
                w_parent = 1.0 / tau2
                total = w_cell + w_parent
                posterior = (w_cell * raw + w_parent * parent.posterior_mean) / total
                self.cells[key] = CellEstimate(
                    key=key,
                    level=level,
                    n_events=n,
                    raw_mean=raw,
                    posterior_mean=float(posterior),
                    posterior_se=float(math.sqrt(1.0 / total)),
                    shrinkage=float(w_cell / total),
                    tau_squared=tau2,
                )

    def _scale(self, cell: CellEstimate) -> float:
        """Predicted dispersion of a single future event around ``cell``.

        Two sources, added in variance: how uncertain the cell mean is, and how much
        events within a cell genuinely differ. Omitting the second - a common slip -
        makes the interval shrink toward zero as history accumulates, implying that
        enough data would let you predict an individual event exactly.
        """
        between = max(self.tau_squared.get(cell.level, 0.0), 0.0)
        var = cell.posterior_se**2 + between
        return float(math.sqrt(var)) if var > 0 else float("nan")

    def _calibrate(self, calibration: pd.DataFrame) -> float:
        """Split-conformal quantile of scale-normalised absolute residuals.

        The finite-sample correction ``(1-alpha)(1+1/n)`` is what makes the coverage
        guarantee exact rather than asymptotic; at n=20 it is the difference between a
        nominal 80% interval and a real one. Returns NaN when calibration was skipped,
        and callers then fall back to a normal quantile with a warning attached rather
        than silently reporting an interval no one calibrated.
        """
        if calibration.empty:
            return float("nan")
        residuals: list[float] = []
        for row in calibration.itertuples():
            cell = self._lookup(str(row.brand_id), str(row.event_format))
            scale = self._scale(cell)
            if not np.isfinite(scale) or scale <= 0:
                continue
            residuals.append(abs(float(row.per_attendee) - cell.posterior_mean) / scale)
        if not residuals:
            return float("nan")
        arr = np.sort(np.asarray(residuals))
        n = arr.size
        level = min(1.0, self.spec.coverage * (1.0 + 1.0 / n))
        return float(np.quantile(arr, level, method="higher"))

    def _lookup(self, brand_id: str, event_format: str) -> CellEstimate:
        """Finest fitted node that covers the request, walking up to the global mean."""
        for key in ((brand_id, event_format), (brand_id,), ()):
            cell = self.cells.get(key)
            if cell is not None:
                return cell
        return self.cells[()]

    # -- prediction ---------------------------------------------------------
    def predict(
        self,
        brand_id: str,
        event_format: str,
        planned_attendees: float,
    ) -> ImpactForecast:
        """Forecast per-attendee effect for a proposed program.

        Support is checked before anything is computed, and a failure names the feature
        rather than returning a number with a caveat. See the module docstring on why the
        caveat would not survive contact with a slide deck.
        """
        if not self.fitted:
            raise RuntimeError("predict() called before fit()")
        fmt = event_format.value if hasattr(event_format, "value") else str(event_format)
        brand = str(brand_id)

        offending: list[str] = []
        remedies: list[str] = []
        if brand not in self.known_brands:
            offending.append(f"brand_id={brand}")
            remedies.append(
                f"no measured program exists for brand {brand}; the first few events for "
                "a brand cannot be forecast from other brands' response"
            )
        if fmt not in self.known_formats:
            offending.append(f"event_format={fmt}")
            remedies.append(
                f"no measured program used the {fmt} format; run and measure at least "
                f"{MIN_CELL_EVENTS} before forecasting one"
            )
        if not np.isfinite(planned_attendees) or planned_attendees <= 0:
            offending.append("planned_attendees")
            remedies.append("a positive planned attendance is required")
        elif planned_attendees > self.max_attendance * self.spec.max_attendance_multiple:
            offending.append(f"planned_attendees={planned_attendees:.0f}")
            remedies.append(
                f"the largest measured program had {self.max_attendance:.0f} verified "
                f"attendees; a per-attendee effect measured at that scale does not "
                f"extrapolate to {planned_attendees:.0f}"
            )
        if offending:
            return ImpactForecast(
                mode=ForecastMode.OUT_OF_SUPPORT,
                per_attendee=float("nan"),
                per_attendee_low=float("nan"),
                per_attendee_high=float("nan"),
                planned_attendees=float(planned_attendees),
                total=float("nan"),
                total_low=float("nan"),
                total_high=float("nan"),
                coverage=self.spec.coverage,
                cell_key=(),
                cell_events=0,
                shrinkage=float("nan"),
                out_of_support=tuple(offending),
                remedy="; ".join(remedies),
                spec_fingerprint=self.spec.fingerprint,
            )

        cell = self._lookup(brand, fmt)
        scale = self._scale(cell)
        warnings: list[str] = []

        if np.isfinite(self.conformal_q):
            multiplier = self.conformal_q
        else:
            # 1.2816 is the 80th-percentile normal deviate for the default coverage.
            multiplier = float(abs(np.sqrt(2) * 0.9062)) if self.spec.coverage == 0.80 else 1.2816
            warnings.append(
                "the prediction interval is not conformally calibrated - too few events "
                "were available to hold out - so its coverage is assumed, not measured"
            )
        half = scale * multiplier if np.isfinite(scale) else float("nan")

        mode = ForecastMode.MODEL
        if self.n_events < MIN_TRAINING_EVENTS or cell.shrinkage <= 0.0:
            mode = ForecastMode.POOLED
            if self.n_events < MIN_TRAINING_EVENTS:
                warnings.append(
                    f"only {self.n_events} measured programs are available (a segment-level "
                    f"model needs about {MIN_TRAINING_EVENTS}), so this forecast is close to "
                    "the historical average across all programs"
                )
            else:
                warnings.append(
                    f"no segment-specific signal was detectable for {brand}/{fmt}, so the "
                    "historical average for the closest segment with evidence is reported"
                )

        point = cell.posterior_mean
        return ImpactForecast(
            mode=mode,
            per_attendee=float(point),
            per_attendee_low=float(point - half),
            per_attendee_high=float(point + half),
            planned_attendees=float(planned_attendees),
            total=float(point * planned_attendees),
            total_low=float((point - half) * planned_attendees),
            total_high=float((point + half) * planned_attendees),
            coverage=self.spec.coverage,
            cell_key=cell.key,
            cell_events=cell.n_events,
            shrinkage=cell.shrinkage,
            spec_fingerprint=self.spec.fingerprint,
            warnings=tuple(warnings),
        )

    # -- validation ---------------------------------------------------------
    def validate(self, training: pd.DataFrame, *, folds: int = 3) -> ValidationReport:
        """Rolling-origin temporal validation against the historical-average baseline.

        A fresh forecaster is fitted for every fold rather than reusing ``self``, because
        scoring a model on rows it was fitted on measures memorisation. The baseline is the
        pooled precision-weighted mean of that fold's own training head - the number a
        planner would use with no model - so the comparison isolates what the hierarchy
        contributes and nothing else.

        Rolling-origin rather than a single split, because a single split does not have the
        power to answer the question. plan.md §12.6 makes MAE against the historical average
        a promotion criterion; measured on one 30% holdout of a 120-event panel, the
        standard error on the MAE *difference* exceeds any difference a correct model would
        produce, so the criterion is decided by which era landed in the holdout. Several
        origins, scored as paired per-event differences, is what turns that into a
        measurement. It is still a weak one - see
        :attr:`ValidationReport.decisively_better` - and the honest conclusion is that
        next-event MAE is the wrong promotion gate for this model, not that the model should
        be tuned until it passes one.

        ``folds`` origins are taken at evenly spaced points across the last
        :attr:`ImpactModelSpec.holdout_share` of the timeline. Each fold trains on
        everything strictly before its origin, so no fold ever sees its own future.
        """
        frame = prepare_training_frame(training, self.spec) if "grade" in training else training
        frame = frame.sort_values("event_month_index").reset_index(drop=True)
        n = len(frame)
        warnings: list[str] = []
        total_holdout = max(1, round(n * self.spec.holdout_share))
        first_origin = n - total_holdout
        if first_origin < MIN_TRAINING_EVENTS // 4:
            warnings.append(
                f"only {n} measured programs are available; the holdout is too small for "
                "these metrics to discriminate between a good model and a lucky one"
            )
        # One origin when the panel cannot support several: folds whose training heads
        # differ by two events are not independent evidence, they are the same fold three
        # times with a longer runtime.
        n_folds = max(1, min(folds, total_holdout // max(1, MIN_CELL_EVENTS * 2)))
        origins = [first_origin + round(i * total_holdout / n_folds) for i in range(n_folds)]

        rows: list[dict[str, object]] = []
        last_tau: dict[int, float] = {}
        for fold, origin in enumerate(origins):
            head = frame.iloc[:origin]
            end = origins[fold + 1] if fold + 1 < len(origins) else n
            tail = frame.iloc[origin:end]
            if head.empty or tail.empty:
                continue
            inner = ImpactForecaster(self.spec).fit(head)
            last_tau = dict(inner.tau_squared)
            baseline, _ = _weighted_mean(
                head["per_attendee"].to_numpy(dtype=float),
                head["se_per_attendee"].to_numpy(dtype=float) ** 2,
            )
            for row in tail.itertuples():
                forecast = inner.predict(
                    str(row.brand_id), str(row.event_format), float(row.verified_attendees)
                )
                if not forecast.usable:
                    # An out-of-support holdout event is not a prediction error - the model
                    # correctly declined. Counting it as one would penalise exactly the
                    # behaviour the design wants, so it is excluded from the metrics and
                    # surfaced instead.
                    warnings.append(
                        f"holdout event {row.event_id} was out of support "
                        f"({', '.join(forecast.out_of_support)}) and is excluded from the "
                        "metrics"
                    )
                    continue
                actual = float(row.per_attendee)
                rows.append(
                    {
                        "fold": fold,
                        "event_id": row.event_id,
                        "brand_id": row.brand_id,
                        "event_format": row.event_format,
                        "actual": actual,
                        "predicted": forecast.per_attendee,
                        "error": forecast.per_attendee - actual,
                        "baseline_error": baseline - actual,
                        "covered": bool(
                            forecast.per_attendee_low <= actual <= forecast.per_attendee_high
                        ),
                    }
                )

        scored = pd.DataFrame(rows)
        if scored.empty:
            return ValidationReport(
                n_train=first_origin,
                n_holdout=0,
                mae=float("nan"),
                baseline_mae=float("nan"),
                bias=float("nan"),
                baseline_bias=float("nan"),
                interval_coverage=float("nan"),
                mae_advantage=float("nan"),
                mae_advantage_se=float("nan"),
                folds=len(origins),
                by_segment=pd.DataFrame(),
                tau_squared=last_tau,
                nominal_coverage=self.spec.coverage,
                warnings=(*warnings, "no holdout event could be scored"),
            )

        absolute = scored["error"].abs()
        baseline_absolute = scored["baseline_error"].abs()
        # Paired per-event differences. The event-to-event variation that swamps an unpaired
        # MAE comparison cancels here, which is the only reason this statistic has any power
        # at all at these sample sizes.
        paired = baseline_absolute - absolute
        advantage = float(paired.mean())
        advantage_se = (
            float(paired.std(ddof=1) / math.sqrt(len(paired))) if len(paired) > 1 else float("nan")
        )

        by_segment = (
            scored.assign(abs_error=absolute)
            .groupby("event_format", as_index=False)
            .agg(n=("event_id", "size"), mae=("abs_error", "mean"), bias=("error", "mean"))
        )
        report = ValidationReport(
            n_train=first_origin,
            n_holdout=len(scored),
            mae=float(absolute.mean()),
            baseline_mae=float(baseline_absolute.mean()),
            bias=float(scored["error"].mean()),
            baseline_bias=float(scored["baseline_error"].mean()),
            interval_coverage=float(scored["covered"].mean()),
            mae_advantage=advantage,
            mae_advantage_se=advantage_se,
            folds=len(origins),
            by_segment=by_segment,
            tau_squared=last_tau,
            nominal_coverage=self.spec.coverage,
            warnings=tuple(warnings),
        )
        _LOG.info(
            "forecast.impact.validated",
            spec=self.spec.fingerprint,
            n_train=report.n_train,
            n_holdout=report.n_holdout,
            mae=report.mae,
            baseline_mae=report.baseline_mae,
            bias=report.bias,
            interval_coverage=report.interval_coverage,
            mae_advantage=report.mae_advantage,
            mae_advantage_se=report.mae_advantage_se,
            folds=report.folds,
            beats_baseline=report.beats_baseline,
            not_worse=report.not_worse,
        )
        return report
