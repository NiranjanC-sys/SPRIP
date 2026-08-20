"""Evidence grading: ten pre-registered gates in, one word out.

The grade is a **deterministic function of measurements against thresholds fixed before
the data was seen**. It is not a model output, not a calibrated probability, and nothing
in it is learned. That is a deliberate product decision, not a modelling shortcut:

*  A learned confidence score would have to be trained on labelled examples of "this
   causal estimate turned out to be right", and no such labels exist. Any number
   produced that way would be a plausible-looking fabrication, and a commercial team
   would reasonably treat it as authoritative.
*  A grade computed from named gates can be *explained*. "MODERATE, because 71% of
   attendees found a match inside the caliper and the bar is 70%, and because the
   direction does not survive a confounder as strong as prior-quarter call volume" is a
   sentence someone can argue with, audit, and act on.
*  Thresholds fixed in :class:`~.spec.GateThresholds` and versioned with the spec
   cannot be tuned after the fact to make a disappointing result look better. That is
   the whole point of pre-registration, and it is the difference between a measurement
   system and a marketing one.

The four grades and what each licenses
--------------------------------------
``STRONG``       Every gate passes, the design needed little help to balance, and the
                 direction survives a bias bound benchmarked on the strongest observed
                 confounder. This licenses a causal claim in a business review.
``MODERATE``     Every gate passes, but design quality is compromised somewhere - heavy
                 reweighting was needed, or the control strategy is structurally weaker.
                 The number is usable for planning; the causal language should be
                 hedged.
``DIRECTIONAL``  A credibility gate failed, or the direction does not survive the bias
                 bound. The sign is the only thing worth reading; do not quote the
                 magnitude, and do not put it in a budget model.
``NOT_ESTIMABLE`` A feasibility gate failed. There is no estimate. This is a first-class
                 outcome, not an error, and it is displayed with the reasons attached -
                 see :func:`~.estimator.estimate_att` on why refusals carry diagnostics.

Feasibility versus credibility
------------------------------
The ten gates split into two kinds, and conflating them is the most common way a
system like this misleads. Feasibility gates ask *can this be estimated at all* - enough
attendees, enough controls, enough overlap, enough of the cohort retained. Failing one
means there is no number, so the grade collapses to ``NOT_ESTIMABLE``. Credibility gates
ask *should this number be believed* - balance, parallel trends, a null placebo, a stable
specification. Failing one means there is a number and it should not be trusted beyond
its sign, so the grade collapses to ``DIRECTIONAL``. A system that treated a failed
placebo as "no estimate" would hide the sign; one that treated eight attendees as
"directional" would report noise as a direction.

Where the refinement is and is not trusted
------------------------------------------
:mod:`.balancing` reweights matched controls until the balance moments hold exactly, so
:attr:`~.matching.MatchResult.worst_smd` is near zero whatever the design did.
``COVARIATE_BALANCE`` still reads that refined figure, and that is correct: the estimate
is computed on those weights, so the analysed sample genuinely is balanced. But needing
a large reweighting to get there is a fact about the design, so
:attr:`~.matching.MatchResult.worst_smd_unrefined` and the effective-sample-size cost
cap the grade at ``MODERATE`` instead. ``PARALLEL_PRE_TREND`` is treated differently
again - it reads the *unrefined* figure, because the pre-trend is the only observable
proxy for an assumption about the post period, and a proxy the solver was instructed to
satisfy has stopped being a proxy. See :data:`~.matching.TREND_COVARIATES`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import structlog

from speaker_roi_core.enums import EvidenceGate, EvidenceGrade, ExclusionReason

from .balancing import MIN_ESS_SHARE
from .estimator import EstimatorResult
from .matching import MatchResult
from .panel import Cohort
from .propensity import PropensityResult
from .sensitivity import SensitivityReport
from .spec import EstimatorSpec

__all__ = [
    "CREDIBILITY_GATES",
    "FEASIBILITY_GATES",
    "MIN_ESS_FOR_STRONG",
    "UNREFINED_SMD_MULTIPLE",
    "EvidenceReport",
    "GateOutcome",
    "grade_evidence",
]

_LOG = structlog.get_logger(__name__)

#: Gates that decide whether an estimate exists. Any failure yields
#: :attr:`~speaker_roi_core.enums.EvidenceGrade.NOT_ESTIMABLE`.
FEASIBILITY_GATES: tuple[EvidenceGate, ...] = (
    EvidenceGate.MIN_TREATED_SAMPLE,
    EvidenceGate.MIN_CONTROL_SAMPLE,
    EvidenceGate.OUTCOME_COVERAGE,
    EvidenceGate.PROPENSITY_OVERLAP,
    EvidenceGate.MATCHED_RETENTION,
)

#: Gates that decide whether an existing estimate can be believed beyond its sign. Any
#: failure yields :attr:`~speaker_roi_core.enums.EvidenceGrade.DIRECTIONAL`.
CREDIBILITY_GATES: tuple[EvidenceGate, ...] = (
    EvidenceGate.COVARIATE_BALANCE,
    EvidenceGate.PARALLEL_PRE_TREND,
    EvidenceGate.PLACEBO_NULL,
    EvidenceGate.SENSITIVITY_STABILITY,
    EvidenceGate.CONTAMINATION,
)

#: Effective-sample-size share below which the entropy-balancing refinement did enough
#: of the work that the design cannot be called strong. Set well above
#: :data:`~.balancing.MIN_ESS_SHARE`, which is the point at which the refinement is
#: refused outright: between the two the estimate is real but leaning on a reweighting,
#: which is exactly what ``MODERATE`` is for.
MIN_ESS_FOR_STRONG = 0.75

#: Multiple of the balance threshold that matching alone may leave behind before the
#: grade is capped. At 2.0 with the default 0.10 bound, matching that stalled above
#: 0.20 standardised units was rescued rather than successful. Measured on synthetic
#: cohorts, matching alone reaches 0.095-0.138, so a healthy design sits under this and
#: a badly overlapping one does not.
UNREFINED_SMD_MULTIPLE = 2.0

#: Exclusion reasons that mean the outcome panel could not support the unit, as opposed
#: to the design deciding not to use it. ``OUTCOME_COVERAGE`` is measured against these.
_COVERAGE_REASONS: frozenset[str] = frozenset(
    {
        ExclusionReason.OUTCOME_SUPPRESSED.value,
        ExclusionReason.INSUFFICIENT_PRE_HISTORY.value,
        ExclusionReason.INSUFFICIENT_POST_COVERAGE.value,
    }
)


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """One gate, what was measured, and what it was measured against."""

    gate: EvidenceGate
    passed: bool
    observed: float
    threshold: float
    #: ``">="`` for a floor, ``"<="`` for a ceiling. Stored rather than inferred so the
    #: UI can render the comparison without knowing each gate's polarity.
    comparison: str
    #: One sentence, in the language of the business, for the Method panel and the
    #: refusal message. Written for every gate, not only failures: a reader deciding
    #: how much to trust a pass needs to see how close it was.
    detail: str
    #: True when this gate could not be evaluated - the measurement was unavailable
    #: rather than out of bounds. Treated as a failure, because a gate that silently
    #: passes when its input is missing is worse than no gate.
    indeterminate: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceReport:
    """The grade, every gate behind it, and the reasons it is not higher."""

    grade: EvidenceGrade
    gates: tuple[GateOutcome, ...]
    #: Failed gates, in declaration order.
    failed: tuple[EvidenceGate, ...]
    #: Human-readable reasons the grade is not the next one up. Empty at ``STRONG``.
    #: These are what the UI shows beside the badge; a grade without them invites the
    #: reader to invent their own explanation.
    caps: tuple[str, ...]
    #: The interval a decision should be made from: sampling error widened by the bias
    #: bound. Copied from :class:`~.sensitivity.SensitivityReport` so a consumer needs
    #: one object rather than two, and cannot pair a grade with the narrow interval.
    interval_low: float
    interval_high: float
    interval_basis: str = "sampling error widened by a benchmarked confounder bound"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def estimable(self) -> bool:
        return self.grade is not EvidenceGrade.NOT_ESTIMABLE

    def by_gate(self, gate: EvidenceGate) -> GateOutcome | None:
        return next((outcome for outcome in self.gates if outcome.gate is gate), None)

    def to_rows(self) -> pd.DataFrame:
        """Gate outcomes as a frame, for the stored analysis run and the API."""
        return pd.DataFrame(
            [
                {
                    "gate": outcome.gate.value,
                    "passed": outcome.passed,
                    "observed": outcome.observed,
                    "threshold": outcome.threshold,
                    "comparison": outcome.comparison,
                    "detail": outcome.detail,
                    "indeterminate": outcome.indeterminate,
                }
                for outcome in self.gates
            ],
            columns=[
                "gate",
                "passed",
                "observed",
                "threshold",
                "comparison",
                "detail",
                "indeterminate",
            ],
        )


def _floor(gate: EvidenceGate, observed: float, threshold: float, detail: str) -> GateOutcome:
    """A gate the observed value must reach or exceed."""
    if not np.isfinite(observed):
        return GateOutcome(gate, False, observed, threshold, ">=", detail, indeterminate=True)
    return GateOutcome(gate, observed >= threshold, float(observed), threshold, ">=", detail)


def _ceiling(gate: EvidenceGate, observed: float, threshold: float, detail: str) -> GateOutcome:
    """A gate the observed value must stay at or below.

    A NaN observation is indeterminate and therefore failing, with one exception that
    the caller handles explicitly: a ratio whose denominator is legitimately near zero,
    where the test has nothing to say rather than something bad to say.
    """
    if not np.isfinite(observed):
        return GateOutcome(gate, False, observed, threshold, "<=", detail, indeterminate=True)
    return GateOutcome(gate, observed <= threshold, float(observed), threshold, "<=", detail)


def _coverage(cohort: Cohort) -> float:
    """Share of considered invitations the outcome panel could actually support.

    Measured over every considered invitation rather than over the treated arm alone,
    because the exclusion ledger records ``(event, prescriber, reason)`` and not which
    arm the unit would have joined - arm is only decided after these exclusions run.
    The two differ, and the direction is knowable: attendees have denser outcome
    history than non-attendees on average, so a figure computed over both arms is the
    conservative one. Worth stating rather than quietly reporting a number the brief
    defines differently.
    """
    if cohort.n_invitations_considered <= 0:
        return float("nan")
    if cohort.exclusions.empty:
        return 1.0
    lost = int(cohort.exclusions["reason"].isin(_COVERAGE_REASONS).sum())
    return 1.0 - lost / cohort.n_invitations_considered


def _contamination(cohort: Cohort) -> float:
    """Share of considered invitations dropped for a second exposure in the window."""
    if cohort.n_invitations_considered <= 0:
        return float("nan")
    if cohort.exclusions.empty:
        return 0.0
    hits = int((cohort.exclusions["reason"] == ExclusionReason.OVERLAPPING_EXPOSURE.value).sum())
    return hits / cohort.n_invitations_considered


def _worst_adjusted_smd(matches: MatchResult) -> float:
    """Worst standardised difference among covariates left to the outcome model.

    Reported alongside the matched figure because the two are gated at different
    bounds for different reasons, and a reader who sees only the matched number has no
    way to know an ``ADJUSTED`` covariate is sitting at 0.24.
    """
    balance = matches.balance
    if balance.empty or "role" not in balance:
        return float("nan")
    adjusted = balance[balance["role"] == "ADJUSTED"]
    if adjusted.empty:
        return 0.0
    return float(adjusted["smd_after"].max(skipna=True))


def grade_evidence(
    cohort: Cohort,
    propensity: PropensityResult,
    matches: MatchResult,
    primary: EstimatorResult,
    sensitivity: SensitivityReport,
    spec: EstimatorSpec,
) -> EvidenceReport:
    """Evaluate every gate and reduce them to a grade.

    Never raises. A cohort that cannot be estimated returns a report whose grade is
    ``NOT_ESTIMABLE`` and whose gates explain which measurement fell short - which is
    the display the product needs, and something an exception cannot provide.
    """
    gates_spec = spec.gates
    outcomes: list[GateOutcome] = []
    warnings: list[str] = []

    # --- feasibility -------------------------------------------------------
    outcomes.append(
        _floor(
            EvidenceGate.MIN_TREATED_SAMPLE,
            primary.n_treated,
            gates_spec.min_treated,
            f"{primary.n_treated} analysable attendees against a floor of {gates_spec.min_treated}",
        )
    )
    outcomes.append(
        _floor(
            EvidenceGate.MIN_CONTROL_SAMPLE,
            primary.n_controls,
            gates_spec.min_controls,
            f"{primary.n_controls} matched controls against a floor of {gates_spec.min_controls}",
        )
    )
    coverage = _coverage(cohort)
    outcomes.append(
        _floor(
            EvidenceGate.OUTCOME_COVERAGE,
            coverage,
            gates_spec.min_outcome_coverage,
            f"{coverage:.0%} of considered invitations had a usable prescribing series "
            f"across both windows (floor {gates_spec.min_outcome_coverage:.0%})",
        )
    )
    outcomes.append(
        _floor(
            EvidenceGate.PROPENSITY_OVERLAP,
            propensity.overlap,
            gates_spec.min_propensity_overlap,
            f"{propensity.overlap:.0%} of attendees fall inside the control score range "
            f"(floor {gates_spec.min_propensity_overlap:.0%})",
        )
    )
    outcomes.append(
        _floor(
            EvidenceGate.MATCHED_RETENTION,
            matches.retention,
            gates_spec.min_matched_retention,
            f"{matches.retention:.0%} of attendees found a comparable control inside the "
            f"caliper (floor {gates_spec.min_matched_retention:.0%})",
        )
    )

    # --- credibility -------------------------------------------------------
    # The refined figure, deliberately: the estimate is computed on the refined weights,
    # so this is balance in the sample that produced the number. What it took to get
    # there is a grade cap further down, not a gate.
    adjusted_worst = _worst_adjusted_smd(matches)
    outcomes.append(
        _ceiling(
            EvidenceGate.COVARIATE_BALANCE,
            matches.worst_smd,
            gates_spec.max_smd_after_matching,
            f"worst matched covariate difference {matches.worst_smd:.3f} standardised "
            f"units (bound {gates_spec.max_smd_after_matching:.2f}); worst covariate left "
            f"to the outcome model {adjusted_worst:.3f}; matching alone reached "
            f"{matches.worst_smd_unrefined:.3f} before reweighting",
        )
    )
    outcomes.append(
        _ceiling(
            EvidenceGate.PARALLEL_PRE_TREND,
            primary.pre_trend_gap_unrefined,
            gates_spec.max_pre_trend_gap,
            f"the two arms' pre-event prescribing trends differ by "
            f"{primary.pre_trend_gap_unrefined:.4f} log points before balancing "
            f"(bound {gates_spec.max_pre_trend_gap:.2f})",
        )
    )

    # A placebo ratio is NaN when the real estimate is too near zero to divide by. That
    # is not a failure: there is no effect for a spurious one to be compared against.
    # It does mean the test cannot vouch for the design, so it caps the grade below.
    placebo = sensitivity.placebo_ratio
    if np.isfinite(placebo):
        outcomes.append(
            _ceiling(
                EvidenceGate.PLACEBO_NULL,
                placebo,
                gates_spec.max_placebo_ratio,
                f"a placebo run on two pre-event windows finds {placebo:.0%} of the real "
                f"effect (bound {gates_spec.max_placebo_ratio:.0%})",
            )
        )
    else:
        outcomes.append(
            GateOutcome(
                EvidenceGate.PLACEBO_NULL,
                True,
                float("nan"),
                gates_spec.max_placebo_ratio,
                "<=",
                "the estimate is too close to zero for a placebo comparison to mean "
                "anything, so this gate is not evidence either way",
                indeterminate=True,
            )
        )
    # Two ways to fail one gate. The spread bound catches magnitude instability; a sign
    # reversal fails outright regardless of spread, because a variation whose deviation is
    # only 40% but points the other way has moved the one claim a DIRECTIONAL grade is
    # allowed to make. Note that :attr:`~.sensitivity.SensitivityReport.spread` excludes
    # the post-window variations by design - see the comment on them in
    # :func:`~.sensitivity.run_sensitivity` - but the sign check does not, which is how
    # those runs still earn their cost.
    if not sensitivity.sign_stable_across_variants:
        flipped = sensitivity.sign_flips[0] if sensitivity.sign_flips else "a variation"
        outcomes.append(
            GateOutcome(
                EvidenceGate.SENSITIVITY_STABILITY,
                False,
                sensitivity.spread,
                gates_spec.max_sensitivity_spread,
                "<=",
                f"{len(sensitivity.sign_flips)} specification variation(s) reversed the "
                f"direction of the effect ({flipped}); the sign is not stable, which is a "
                "stronger failure than a wide spread",
            )
        )
    else:
        outcomes.append(
            _ceiling(
                EvidenceGate.SENSITIVITY_STABILITY,
                sensitivity.spread,
                gates_spec.max_sensitivity_spread,
                f"the estimate moves at most {sensitivity.spread:.0%} across the "
                f"specification variations (bound {gates_spec.max_sensitivity_spread:.0%})",
            )
        )
    contamination = _contamination(cohort)
    outcomes.append(
        _ceiling(
            EvidenceGate.CONTAMINATION,
            contamination,
            gates_spec.max_contamination,
            f"{contamination:.0%} of considered invitations were dropped for a second "
            f"exposure inside the measurement window (bound "
            f"{gates_spec.max_contamination:.0%})",
        )
    )

    failed = tuple(o.gate for o in outcomes if not o.passed)

    # --- reduce ------------------------------------------------------------
    caps: list[str] = []
    if not primary.estimable:
        grade = EvidenceGrade.NOT_ESTIMABLE
        caps.append("; ".join(primary.warnings) or "the estimator declined to produce a number")
    elif any(o.gate in FEASIBILITY_GATES and not o.passed for o in outcomes):
        grade = EvidenceGrade.NOT_ESTIMABLE
        caps.extend(o.detail for o in outcomes if o.gate in FEASIBILITY_GATES and not o.passed)
    elif any(o.gate in CREDIBILITY_GATES and not o.passed for o in outcomes):
        grade = EvidenceGrade.DIRECTIONAL
        caps.extend(o.detail for o in outcomes if o.gate in CREDIBILITY_GATES and not o.passed)
    elif not sensitivity.sign_survives_bound:
        grade = EvidenceGrade.DIRECTIONAL
        caps.append(
            "the direction does not survive a confounder as strong as "
            f"{sensitivity.benchmark_covariate or 'the strongest measured covariate'}, so "
            "only the sign of this result is safe to read"
        )
    else:
        grade = EvidenceGrade.STRONG
        ess = matches.refinement.ess_share
        if np.isfinite(ess) and ess < MIN_ESS_FOR_STRONG:
            grade = EvidenceGrade.MODERATE
            caps.append(
                f"reweighting to reach balance cost {1 - ess:.0%} of the control arm's "
                f"effective size (a strong design keeps at least "
                f"{MIN_ESS_FOR_STRONG:.0%}, and the refinement is refused below "
                f"{MIN_ESS_SHARE:.0%})"
            )
        unrefined_bound = UNREFINED_SMD_MULTIPLE * gates_spec.max_smd_after_matching
        if (
            np.isfinite(matches.worst_smd_unrefined)
            and matches.worst_smd_unrefined > unrefined_bound
        ):
            grade = EvidenceGrade.MODERATE
            caps.append(
                f"matching on its own left a covariate difference of "
                f"{matches.worst_smd_unrefined:.3f}, above {unrefined_bound:.2f}, so "
                "balance was achieved by reweighting rather than by comparability"
            )
        if not matches.refinement.applied and matches.refinement.reason not in {
            "nothing to balance",
            "one arm is empty",
        }:
            warnings.append(f"balance refinement was refused: {matches.refinement.reason}")

    ceiling = spec.max_evidence_grade
    if _rank(grade) > _rank(ceiling):
        caps.append(
            f"the {spec.control_strategy.value} control strategy caps this analysis at "
            f"{ceiling.value} however clean its diagnostics are"
        )
        grade = ceiling

    if any(o.indeterminate for o in outcomes if o.passed):
        warnings.append(
            "one or more gates could not be evaluated and are reported as not-evidence; "
            "see the gate details"
        )
    warnings.extend(sensitivity.warnings)

    report = EvidenceReport(
        grade=grade,
        gates=tuple(outcomes),
        failed=failed,
        caps=tuple(caps),
        interval_low=sensitivity.robust_total_low,
        interval_high=sensitivity.robust_total_high,
        warnings=tuple(warnings),
    )
    _LOG.info(
        "causal.evidence.graded",
        spec=spec.fingerprint,
        grade=grade.value,
        failed=[gate.value for gate in failed],
        caps=len(caps),
        interval_low=report.interval_low,
        interval_high=report.interval_high,
    )
    return report


#: Grades in order of strength, so a ceiling can be applied without a chain of
#: comparisons. Defined here rather than on the enum because ordering is a property of
#: this decision procedure, not of the vocabulary.
_ORDER: tuple[EvidenceGrade, ...] = (
    EvidenceGrade.NOT_ESTIMABLE,
    EvidenceGrade.DIRECTIONAL,
    EvidenceGrade.MODERATE,
    EvidenceGrade.STRONG,
)


def _rank(grade: EvidenceGrade) -> int:
    return _ORDER.index(grade)
