"""The versioned specification a causal estimate was produced under.

Why this is a stored object rather than a set of function arguments
-------------------------------------------------------------------
An ATT is only interpretable next to the choices that produced it: how long the
post window was, how tight the caliper was, how many controls each attendee got,
what counted as a control at all. Those choices are exactly the ones somebody
will want to revisit six months later when a number is questioned - and if they
live as defaults scattered across function signatures, "what settings produced
the figure in the January board pack?" has no answer.

So the spec is a frozen, hashable object with a content address
(:attr:`EstimatorSpec.fingerprint`). Every stored result references one. Two runs
that agree on the fingerprint are comparable; two that do not are not, and the UI
says so rather than putting them on the same axis. This is what
``analytics.estimator_specs`` holds (plan.md §12.7).

The gate thresholds live here too, for the same reason. A gate is a
*pre-registered* rule: it has to be fixed before the estimate is seen, or it is
not a gate but a negotiation. Storing the thresholds with the spec makes moving
one a visible, versioned act rather than an edit to a constant.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Final

from speaker_roi_core.enums import ControlStrategy, EstimatorKind, EvidenceGrade, OutcomeMetric

__all__ = [
    "DEFAULT_SPEC",
    "SPEC_SCHEMA_VERSION",
    "EstimatorSpec",
    "GateThresholds",
]

#: Bumped when the *meaning* of a field changes, so an old stored spec is never
#: silently reinterpreted under new semantics.
SPEC_SCHEMA_VERSION: Final[str] = "1.0.0"


@dataclass(frozen=True, slots=True)
class GateThresholds:
    """Pre-registered pass/fail rules for :class:`~speaker_roi_core.enums.EvidenceGate`.

    Every value here is a floor or a ceiling on something measurable, and every
    one of them has a failure mode it exists to catch. The defaults are the
    numbers plan.md §12.3 asserts; where the brief left one unstated it is set
    from what the data can actually support, and says so.
    """

    #: Analysable attendees, after every exclusion. Below this the standard error
    #: is wider than any effect worth acting on, so an estimate would be noise
    #: with a decimal point.
    min_treated: int = 8
    #: Matched controls. Asymmetric with ``min_treated`` on purpose: controls are
    #: plentiful (a typical event invites three times as many people as attend),
    #: so a shortfall here signals a matching failure rather than a small event.
    min_controls: int = 16
    #: Share of treated units with a usable pre *and* post outcome window. A
    #: cohort assembled mostly from partial series is measuring panel coverage,
    #: not the program.
    min_outcome_coverage: float = 0.70
    #: Absolute standardised mean difference on every matched covariate, after
    #: matching. 0.10 is the conventional line and the one plan.md §12.3 names.
    max_smd_after_matching: float = 0.10
    #: Share of treated units whose propensity score lies inside the control
    #: distribution's support. Without overlap there is no comparison to make,
    #: only extrapolation from a model.
    min_propensity_overlap: float = 0.80
    #: Share of treated units that found a match inside the caliper. A low value
    #: means the reported ATT describes a self-selected slice of attendees, which
    #: is a different estimand from the one that was asked for.
    min_matched_retention: float = 0.70
    #: Pre-period trend gap between arms, in log points. Not in the brief; set
    #: from measurement. The synthetic DGP - where the truth is known and parallel
    #: trends genuinely holds - produces 0.001-0.019, so 0.05 sits about three
    #: times above the honest noise floor. See "a constraint this DGP places on
    #: the estimator" in ``synthetic/config.py`` for why this is measured in logs:
    #: in raw levels, a multiplicative outcome plus selection on level makes a
    #: nonzero gap unavoidable, and the gate would fire on correct data.
    max_pre_trend_gap: float = 0.05
    #: A placebo run on a shifted pre-period must not find an effect. Expressed
    #: as a share of the real estimate: above this, the machinery manufactures
    #: effects and the real one cannot be told apart from them.
    max_placebo_ratio: float = 0.35
    #: Spread of the sensitivity suite's estimates relative to the primary. A
    #: result that moves 60% when the caliper changes is not a finding.
    max_sensitivity_spread: float = 0.50
    #: Share of treated units dropped for OVERLAPPING_EXPOSURE. Contamination does
    #: not bias what survives, but a high rate means the surviving cohort is
    #: unrepresentative of the program as it was actually run.
    max_contamination: float = 0.35


@dataclass(frozen=True, slots=True)
class EstimatorSpec:
    """Everything that has to be fixed before an ATT means anything.

    ``label`` is free text for humans and is deliberately excluded from the
    fingerprint, so renaming a spec does not orphan the results computed under it.
    """

    label: str = "default-v1"

    # --- estimand ---------------------------------------------------------
    outcome: OutcomeMetric = OutcomeMetric.NRX
    #: Months after the event that count as exposed. The event month itself is in
    #: neither window: attendance happens partway through it, so it is neither
    #: cleanly pre nor cleanly post, and putting it in either one moves the
    #: estimate for a calendar reason rather than a causal one.
    post_window_months: int = 3
    #: Months before the event used for the baseline and the pre-trend test.
    pre_window_months: int = 6
    #: Minimum observed months required in each window for a unit to be
    #: analysable. 4 of 6 pre and 2 of 3 post tolerates the ordinary gaps in a
    #: claims panel without admitting units whose "baseline" is a single month.
    min_pre_months: int = 4
    min_post_months: int = 2
    #: Months of history *before* the baseline window, used to match on and to
    #: balance the prescriber's level. Offsets are
    #: ``[-(pre_window_months + anchor_window_months), -(pre_window_months + 1)]`` -
    #: with the defaults, months -12 to -7.
    #:
    #: This window exists because of a measured bias, and it is the single most
    #: consequential correction in the causal engine. Matching on the *realised*
    #: baseline window - the obvious thing, and what this package did first -
    #: balances a noisy proxy for the prescriber's true level rather than the level
    #: itself. When attendees genuinely sit above the invited non-attendees, the only
    #: controls whose realised baseline equals an attendee's are ones drawn from the
    #: upper tail of their own month-to-month noise. Those controls revert toward
    #: their own mean over the post window while the attendees do not, and the
    #: difference-in-differences picks up the reversion as if it were program impact.
    #:
    #: The algebra is exact rather than approximate. With treated baselines unbiased
    #: for their own level, matching to equal *realised* baselines makes the estimate
    #: ``effect + (lambda_treated - lambda_control)``: the entire true level gap
    #: survives as bias, however well balanced the matching window looks.
    #:
    #: Measured on the synthetic cohort at five seeds, matching on the realised
    #: window drove baseline-window imbalance to 0.037-0.057 SD while the untouched
    #: earlier window stayed at 0.076-0.130 SD - three to four times larger, on every
    #: seed. Multiplying that residual level gap by the post window and the cohort
    #: size accounted for 75-90% of the estimator's measured overstatement.
    #:
    #: The remedy is to match on a window **disjoint** from the one the baseline is
    #: computed over. Two disjoint windows are independent draws around the same
    #: level, so equalising the earlier one carries no information about the later
    #: one's noise, and there is nothing left to borrow. It costs pre-period history:
    #: a unit needs ``pre_window_months + min_anchor_months`` of panel before its
    #: event rather than ``min_pre_months``.
    anchor_window_months: int = 6
    #: Observed months required in the anchor window. Lower than
    #: ``min_pre_months`` because this window is used for a level and a caliper
    #: rather than for a trend, and a level tolerates a sparser series.
    min_anchor_months: int = 3

    # --- identification ---------------------------------------------------
    primary_estimator: EstimatorKind = EstimatorKind.COHORT_TIME_ATT
    control_strategy: ControlStrategy = ControlStrategy.INVITED_NON_ATTENDEE
    #: Controls matched per treated unit. Past about four, the variance gain
    #: flattens while the bias from admitting steadily poorer matches keeps
    #: growing.
    controls_per_treated: int = 3
    #: Caliper in standard deviations of the linear propensity score. Austin
    #: recommends 0.20 for propensity matching used *alone*. This design does not use
    #: it alone: there is a second caliper on baseline volume (below) and an
    #: entropy-balancing refinement after matching (:mod:`~.causal.balancing`), and
    #: both change what the caliper is for.
    #:
    #: Swept over five seeds, holding the volume caliper at 0.50 SD::
    #:
    #:     propensity   matched     control    worst MATCHED   estimate / truth
    #:       caliper   retention   ESS share   SMD (refined)     mean     sd
    #:       0.20 SD      61.7%       93.3%        0.0005         1.35    0.54
    #:       0.35 SD      75.3%       93.0%        0.0008         1.31    0.59
    #:       0.50 SD      81.8%       92.3%        0.0010         1.06    0.67
    #:       0.75 SD      87.2%       90.5%        0.0004         0.82    0.40
    #:       1.00 SD      90.1%       89.1%        0.0006         0.69    0.42
    #:
    #: Two things in that table decide the value, and a third one deliberately does
    #: not.
    #:
    #: Balance no longer decides it. The refinement meets the ``MATCHED`` moments by
    #: construction, so the SMD column is ~0.001 at every width and carries no signal
    #: about the caliper at all. This is why :class:`~.matching.MatchResult` also
    #: reports the *unrefined* worst SMD: otherwise widening the caliper would look
    #: free.
    #:
    #: Accuracy does not decide it either, and saying so is the honest reading rather
    #: than a shrug. The estimate/truth column trends downward across the grid, but
    #: the per-seed standard deviation is 0.40-0.67, so the standard error of each
    #: mean is 0.18-0.30 and no pair of rows here is separated by more than about one
    #: of those. Five seeds cannot resolve this axis; claiming 0.50 as the accuracy
    #: optimum would be reading noise. (That dispersion is not a defect of the
    #: estimator - it is what a single analysis on this much data can actually say,
    #: and it is the reason the reported interval is widened for unmeasured
    #: confounding and the grade is capped below STRONG.)
    #:
    #: What the sweep *can* resolve is retention and the ESS cost, both monotone and
    #: tight across seeds, and they pull in opposite directions: a wider caliper keeps
    #: more treated units but admits poorer counterparts, whose residual imbalance the
    #: refinement then has to remove by concentrating weight - which is exactly what
    #: the falling ESS share measures. 0.50 SD is the tightest width that clears
    #: :attr:`GateThresholds.min_matched_retention` with real margin (81.8% against
    #: 70%) while leaving 92% of the control arm's effective size intact. The margin
    #: matters more than it looks: a per-event or per-brand cut has a fraction of this
    #: cohort's units, and that is where the retention gate will actually bind.
    caliper_sd: float = 0.50
    #: Additional caliper applied directly to prescribing volume over the **anchor**
    #: window, in standard deviations of ``log1p(anchor_nrx_mean)``, on top of the
    #: propensity caliper.
    #:
    #: Why a second caliper at all: a propensity score is a scalar summary, so two
    #: prescribers can share a score while differing sharply on volume, the score
    #: having traded volume off against decile, field activity and competitor share.
    #: Measured before the refinement existed, the propensity caliper alone plateaued
    #: at a worst SMD of 0.12-0.16 and got *worse* when tightened to 0.05 SD - the pool
    #: shrank until small-sample noise reintroduced the imbalance. Volume is the right
    #: thing to constrain directly because it is the confounder with both the largest
    #: SMD and the strongest relationship to the outcome. In logs, for the reason
    #: everything else in this package is: the outcome is multiplicative, so a
    #: 10-script difference means something different at 15 scripts than at 150.
    #:
    #: Why the *anchor* window and not the baseline window - the change that mattered
    #: most in this whole module - is in :attr:`anchor_window_months`.
    #:
    #: Swept over five seeds at a 0.50 SD propensity caliper::
    #:
    #:      volume     matched     control    worst MATCHED   estimate / truth
    #:     caliper   retention   ESS share   SMD (refined)     mean     sd
    #:     0.30 SD      71.9%       94.6%        0.0007         1.25    0.66
    #:     0.50 SD      81.8%       92.3%        0.0010         1.06    0.67
    #:     0.80 SD      87.9%       89.0%        0.0009         0.91    0.61
    #:     1.20 SD      91.3%       84.4%        0.0000         0.85    0.47
    #:
    #: The same reading as the propensity caliper applies: refined balance is flat by
    #: construction, the accuracy trend is inside the five-seed standard error
    #: (0.21-0.30), and what the sweep resolves is the retention-versus-ESS trade. 0.50
    #: SD is the tightest width clearing the 70% retention gate with margin to spare
    #: for the smaller per-event and per-brand cuts, at a 7.7% ESS cost. Loosening to
    #: 1.20 SD would buy 9.5 points of retention for 8 points of effective control
    #: sample - a poor trade, because retention is a gate with a threshold whereas ESS
    #: feeds every standard error the analysis reports.
    covariate_caliper_sd: float = 0.50
    #: Match inside the same event. This is not a refinement, it is what makes the
    #: estimate interpretable: access, competitor pressure and seasonality are
    #: shared by everyone in a brand-region-month, so a control drawn from a
    #: different event carries a different common shock, and the difference
    #: between the two units is then that shock rather than the program.
    match_within_event: bool = True
    #: Whether a control may serve more than one treated unit. With replacement is
    #: less biased - every treated unit gets its nearest available control - at
    #: the cost of correlated matched sets, which the cluster-robust variance
    #: below already accounts for.
    match_with_replacement: bool = True
    #: Exclude units whose *pre* window already contains a verified same-brand
    #: attendance, in either arm. The theory is sound: a program's effect decays
    #: with a half-life measured in months, so an earlier one leaves a tail inside
    #: this unit's baseline, inflating its level and putting a slope in it - the
    #: mirror image of the forward-looking contamination rule.
    #:
    #: **Off by default, because measurement did not support it.** On the synthetic
    #: panel, where parallel trends genuinely holds and the truth is known, turning
    #: it on cost 20% of the cohort and made the pre-trend gap *worse* on four of
    #: five seeds (mean |gap| 0.010 -> 0.017 log points): with no bias to remove,
    #: the smaller sample simply estimated the same zero less precisely. Both
    #: values sit far inside ``max_pre_trend_gap``, so identification was never the
    #: binding consideration here and the cost was the only real effect.
    #:
    #: It stays available, and the sensitivity suite runs it as
    #: ``ALTERNATE_CONTROL_DEFINITION``, because the argument for it is about a
    #: property of *real* data that the generator does not reproduce: in practice
    #: prior attendance strongly predicts the next invitation, so the tail is
    #: correlated with treatment in a way it deliberately is not here. If the
    #: estimate moves materially when this is switched on, that correlation is
    #: present in the tenant's data and the primary estimate should not be trusted
    #: without it.
    exclude_prior_exposure: bool = False

    # --- inference --------------------------------------------------------
    #: Clustering unit for the variance. Prescribers appear at several events and a
    #: control may be reused, so treating matched sets as independent understates
    #: the standard error, by a factor of two or more when a few high-volume
    #: prescribers dominate the cohort.
    cluster_on: str = "hcp_id"
    confidence_level: float = 0.95
    #: Block bootstrap replications. Blocks are clusters, so the resample
    #: preserves the within-prescriber correlation the analytic variance also has
    #: to model.
    bootstrap_replications: int = 400
    bootstrap_seed: int = 20260819

    gates: GateThresholds = field(default_factory=GateThresholds)

    def __post_init__(self) -> None:
        if self.post_window_months < 1 or self.pre_window_months < 2:
            raise ValueError("post window needs >=1 month and pre window >=2 for a trend test")
        if self.min_pre_months > self.pre_window_months:
            raise ValueError("min_pre_months cannot exceed pre_window_months")
        if self.min_post_months > self.post_window_months:
            raise ValueError("min_post_months cannot exceed post_window_months")
        if self.anchor_window_months < 1:
            raise ValueError("anchor_window_months must be at least 1")
        if self.min_anchor_months > self.anchor_window_months:
            raise ValueError("min_anchor_months cannot exceed anchor_window_months")
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must be in (0, 1)")
        if self.covariate_caliper_sd <= 0:
            raise ValueError("covariate_caliper_sd must be positive; use a large value to disable")
        if self.caliper_sd <= 0 or self.controls_per_treated < 1:
            raise ValueError("caliper_sd must be positive and controls_per_treated >= 1")

    @property
    def pre_offsets(self) -> tuple[int, ...]:
        """Month offsets in the baseline window; the event month is excluded."""
        return tuple(range(-self.pre_window_months, 0))

    @property
    def anchor_offsets(self) -> tuple[int, ...]:
        """Month offsets in the anchor window, strictly earlier than the baseline."""
        first = -(self.pre_window_months + self.anchor_window_months)
        return tuple(range(first, -self.pre_window_months))

    @property
    def post_offsets(self) -> tuple[int, ...]:
        """Month offsets in the exposed window; the event month is excluded."""
        return tuple(range(1, self.post_window_months + 1))

    @property
    def max_evidence_grade(self) -> EvidenceGrade:
        """Ceiling imposed by the control strategy, before any gate is evaluated.

        A target-universe comparison cannot yield STRONG evidence however clean
        its diagnostics look, because the comparison group was never invited and
        therefore differs on the unobserved reasons people get invited at all.
        """
        return self.control_strategy.max_evidence_grade

    def to_dict(self) -> dict:
        """JSON-ready form, for the stored spec row and the audit trail."""
        return {"schema_version": SPEC_SCHEMA_VERSION, **asdict(self)}

    @property
    def fingerprint(self) -> str:
        """Content address of every field that changes the answer.

        ``label`` is excluded so a rename is not a new spec. Everything else is
        included, the gate thresholds among them: loosening a gate changes which
        results are publishable, which is precisely the kind of change that must
        not be invisible.
        """
        payload = self.to_dict()
        payload.pop("label", None)
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def variant(self, label: str, **changes: object) -> EstimatorSpec:
        """A modified copy, for the sensitivity suite.

        Sensitivity analysis is *the same estimator under a different spec*, so it
        goes through the same construction path and earns its own fingerprint,
        rather than reaching past the spec to poke at internals.
        """
        return replace(self, label=label, **changes)  # type: ignore[arg-type]


#: The published default. Named, so a result can record which spec it used even
#: when nobody chose one explicitly.
DEFAULT_SPEC: Final[EstimatorSpec] = EstimatorSpec()
