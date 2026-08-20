"""Causal measurement: cohorts, propensity, matching, ATT, and the gates around them.

The pipeline is a fixed order, and each stage hands the next one both its output and
the reasons it excluded anything, so a number reaching the surface can always be
traced back to the population it came from::

    build_cohort      -> Cohort        (units, monthly panel, anchor panel, ledger)
    build_features    -> DataFrame     (pre-event covariates only; leakage asserted)
    fit_propensity    -> scores        (cross-fitted, with common-support flags)
    match_cohort      -> MatchResult   (matched sets, refined weights, balance table)
    estimate_att      -> EstimatorResult (cohort-time ATT, or an explained refusal)
    run_sensitivity   -> SensitivityReport (robustness battery, bias-bounded range)
    grade_evidence    -> EvidenceReport  (ten gates; the grade, and what it licenses)
    compute_roi       -> RoiResult       (money, or an explained refusal)

Two design decisions in here are easy to undo by accident, so they are named at the
top level rather than buried:

**Matching balances an earlier window than the one the estimate differences.** See
:attr:`~.spec.EstimatorSpec.anchor_window_months`. Matching on the realised baseline
window inflated the estimate to roughly four times the known truth on synthetic data
where the truth is available, and it did so while the balance table looked excellent.

**The balance gate is not the whole balance story.** :mod:`.balancing` meets the
matched moments by construction, so :attr:`~.matching.MatchResult.worst_smd` reads
near zero regardless of design quality. The informative numbers are
:attr:`~.matching.MatchResult.worst_smd_unrefined` and
:attr:`~.balancing.BalanceRefinement.ess_share`. The same trap applies to the
parallel-trends gate, which is why the estimator reads
:attr:`~.estimator.EstimatorResult.pre_trend_gap_unrefined` and not the refined figure:
:data:`~.matching.TREND_COVARIATES` is now part of the constraint set, so the refined
gap is small by instruction.
"""

from __future__ import annotations

from .balancing import BalanceRefinement, entropy_balance
from .estimator import EstimatorResult, estimate_att
from .evidence import (
    CREDIBILITY_GATES,
    FEASIBILITY_GATES,
    MIN_ESS_FOR_STRONG,
    UNREFINED_SMD_MULTIPLE,
    EvidenceReport,
    GateOutcome,
    grade_evidence,
)
from .features import (
    BASELINE_WINDOW_LEVELS,
    FEATURE_COLUMNS,
    MATCHING_COVARIATES,
    PROPENSITY_COLUMNS,
    assert_no_leakage,
    build_features,
)
from .matching import (
    DEFERRED_COVARIATES,
    MATERIALITY_SD,
    OFFSET_COVARIATES,
    TREND_COVARIATES,
    MatchResult,
    balance_table,
    match_cohort,
)
from .panel import Cohort, PanelFrames, build_cohort
from .propensity import PropensityResult, fit_propensity
from .roi import (
    PUBLISHABLE_GRADES,
    ContributionComponents,
    EventCost,
    FinanceAssumption,
    RoiResult,
    RoiScenario,
    compute_roi,
    select_assumption,
)
from .sensitivity import SensitivityReport, SensitivityRun, run_sensitivity
from .spec import DEFAULT_SPEC, EstimatorSpec, GateThresholds

__all__ = [
    "BASELINE_WINDOW_LEVELS",
    "CREDIBILITY_GATES",
    "DEFAULT_SPEC",
    "DEFERRED_COVARIATES",
    "FEASIBILITY_GATES",
    "FEATURE_COLUMNS",
    "MATCHING_COVARIATES",
    "MATERIALITY_SD",
    "MIN_ESS_FOR_STRONG",
    "OFFSET_COVARIATES",
    "PROPENSITY_COLUMNS",
    "PUBLISHABLE_GRADES",
    "TREND_COVARIATES",
    "UNREFINED_SMD_MULTIPLE",
    "BalanceRefinement",
    "Cohort",
    "ContributionComponents",
    "EstimatorResult",
    "EstimatorSpec",
    "EventCost",
    "EvidenceReport",
    "FinanceAssumption",
    "GateOutcome",
    "GateThresholds",
    "MatchResult",
    "PanelFrames",
    "PropensityResult",
    "RoiResult",
    "RoiScenario",
    "SensitivityReport",
    "SensitivityRun",
    "assert_no_leakage",
    "balance_table",
    "build_cohort",
    "build_features",
    "compute_roi",
    "entropy_balance",
    "estimate_att",
    "fit_propensity",
    "grade_evidence",
    "match_cohort",
    "run_sensitivity",
    "select_assumption",
]
