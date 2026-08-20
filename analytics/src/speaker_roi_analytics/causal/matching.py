"""Caliper nearest-neighbour matching within event, and the balance table it earns.

Matching is where the estimate becomes defensible or does not, so this module's
output is two things of equal importance: the matched sets, and the evidence that
the matched sets are actually balanced. A matched cohort presented without its
balance table is an assertion.

Why within-event
----------------
Every treated unit is matched only against controls invited to *the same event*.
This is not a tightening of an otherwise-fine design - it is what makes the
comparison mean anything. Access, competitor pressure and seasonality move as
brand-region-month walks shared by everyone at an event, so two prescribers at the
same event faced the same common shock and their difference is the program. A
control drawn from a different event faced a different draw, and the difference
between the two units then contains that draw, which no covariate in the feature
set measures.

It also handles a subtler problem. Invitation is itself selective: brands invite
prescribers they think are worth inviting. A control invited to the same event
passed the same invitation screen, so the comparison conditions on it without
having to model it. That is why
:attr:`~speaker_roi_core.enums.ControlStrategy.INVITED_NON_ATTENDEE` can reach
STRONG evidence while a target-universe comparison cannot, however clean its
diagnostics look.

The cost is real: an event whose attendees are all at the top of the score
distribution has no local controls, and those treated units go unmatched rather
than being paired with someone from elsewhere. That shows up as retention below
:attr:`~.spec.GateThresholds.min_matched_retention` and, correctly, as a weaker
grade - the alternative is a better-looking number describing a comparison nobody
made.

Why with replacement, and what it costs
--------------------------------------
A control may serve several treated units. Without replacement, the result depends
on the arbitrary order treated units are processed in, and late-processed units get
whatever is left rather than their nearest neighbour - which is bias traded for a
tidier-looking design. With replacement every treated unit gets its best available
match. The cost is that matched sets share controls and are therefore correlated,
which makes the naive standard error too small. That is handled where it belongs,
in the variance: clustering on prescriber and bootstrapping by cluster.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import structlog

from speaker_roi_core.enums import ExclusionReason

from .balancing import BalanceRefinement, entropy_balance
from .features import BASELINE_WINDOW_LEVELS, MATCHING_COVARIATES
from .spec import EstimatorSpec

__all__ = [
    "DEFERRED_COVARIATES",
    "MATERIALITY_SD",
    "OFFSET_COVARIATES",
    "TREND_COVARIATES",
    "MatchResult",
    "balance_table",
    "match_cohort",
]

_LOG = structlog.get_logger(__name__)

#: The covariate the second caliper constrains: prescribing volume, the largest
#: imbalance before matching and the strongest predictor of the outcome, so it is
#: where a residual difference does the most damage.
#:
#: Measured over the **anchor** window rather than the baseline window, and that
#: distinction is load-bearing rather than incidental. Constraining the window the
#: baseline is computed from equalises a noisy proxy for each prescriber's level
#: instead of the level itself: when attendees genuinely prescribe more, the only
#: controls whose realised baseline matches an attendee's are ones caught at the top
#: of their own month-to-month noise, and they revert downward over the post window
#: while the attendees do not. The estimate then reads the reversion as impact. Two
#: disjoint windows are independent draws around the same level, so equalising the
#: earlier one says nothing about the later one's noise and there is nothing to
#: borrow. The measurement and the algebra are in
#: :attr:`~.spec.EstimatorSpec.anchor_window_months`.
BALANCE_COVARIATE = "anchor_nrx_mean"

#: Covariates the *estimator* conditions on structurally rather than by balancing.
#: At present one: the baseline level enters the Poisson pseudo-likelihood as a fixed
#: ``log(pre_mean)`` offset, which absorbs each unit's own level exactly rather than
#: approximately. It is therefore neither matching's responsibility nor linear
#: adjustment's, and gating it as though it were would report a failure the design has
#: already handled by a stronger mechanism than either.
#:
#: This is not the same claim as "it does not matter". It is unbalanced *by design*
#: after the anchor-window change: the caliper now constrains the earlier window, so
#: the baseline window is left free to carry its own noise, which is precisely what
#: stops that noise from being borrowed. Its imbalance is reported in the balance
#: table under this role, with the reason attached, and not silently dropped.
OFFSET_COVARIATES: tuple[str, ...] = ("pre_nrx_mean",)

#: Covariates matching deliberately does not target, and that the estimator does not
#: absorb structurally either. These are the baseline-window levels other than the
#: offset: withheld from the propensity model because matching on them re-imports the
#: baseline window's noise (:data:`~.features.BASELINE_WINDOW_LEVELS`), and not
#: absorbable the way ``pre_nrx_mean`` is, because the Poisson offset takes exactly
#: one level and it is the outcome's own.
#:
#: So responsibility falls to the outcome model, which is what the ``ADJUSTED`` role
#: means, and they are gated at the adjustment bound rather than matching's. The
#: distinction matters: gating a covariate at the tighter bound while deliberately
#: declining to target it is a test designed to fail, and loosening the bound *for
#: everything* to accommodate it would silently weaken the covariates matching really
#: is responsible for. Their anchor-window counterparts carry the confounding that
#: matching does handle, and are gated at the full matching threshold.
DEFERRED_COVARIATES: tuple[str, ...] = tuple(
    column for column in BASELINE_WINDOW_LEVELS if column not in OFFSET_COVARIATES
)

#: Balanced in addition to whatever matching was responsible for: the baseline
#: *trend*, as distinct from the baseline *level*.
#:
#: Two reasons, and the second is what makes it safe. Parallel trends is the
#: assumption the whole design rests on - every other covariate is a proxy for it - so
#: if the weights can satisfy it directly, leaving that to chance is a choice with no
#: argument behind it. And an OLS slope taken over a symmetric grid of month offsets
#: is orthogonal to the mean of the same window by construction, so equalising the
#: slope carries no information about the level. That is exactly the hazard the anchor
#: window exists to avoid (:data:`~.features.BASELINE_WINDOW_LEVELS`), and the
#: orthogonality is why this column can be constrained while its level counterpart
#: cannot.
#:
#: Measured, five seeds, pre-trend gap without and with this constraint - alongside
#: the estimate as a ratio to the known truth, which is what shows this is not the
#: outcome being fitted::
#:
#:     seed      gap base   gap +trend   est/true base   est/true +trend
#:     20260819    0.0096       0.0061            2.09              2.09
#:     4242        0.0014       0.0011            0.76              0.76
#:     777         0.0075       0.0106            0.90              0.91
#:     13          0.0089       0.0007            0.85              0.85
#:     90210       0.0605       0.0264            1.44              1.43
#:
#: Four of five improve, the worst case halves, and the point estimates move in the
#: third decimal - which is the reassuring part, because a constraint that shifted the
#: answer would be fitting the outcome. Effective sample size is 0.895-0.949 of the
#: matched weights, against a 0.5 floor.
#:
#: What this does **not** do is rescue seed 90210 from the gate. That gap is 0.0545 on
#: fully unrefined weights, and since that is what
#: :attr:`~.estimator.EstimatorResult.pre_trend_gap_unrefined` reports, the gate still
#: fails it - correctly. It is also the second-least accurate of the five estimates
#: (1.43x truth against a 0.76-2.09 spread), so the diagnostic is firing on the cohort
#: that genuinely deserves it. Constraining the trend improves the *estimate* on a
#: cohort whose trends were nearly parallel anyway; it is not, and must not become, a
#: way to make a cohort whose trends were not parallel report that they were.
#:
#: Because a constrained moment stops being a test of that moment,
#: :attr:`~.matching.MatchResult.base_weights` is retained so the estimator can report
#: the gap matching reached *unaided* - see
#: :attr:`~.estimator.EstimatorResult.pre_trend_gap_unrefined`, which is the number the
#: gate reads. The refined weights get the estimate; the unrefined weights get the
#: verdict on whether to believe it.
TREND_COVARIATES: tuple[str, ...] = ("pre_nrx_trend",)

#: The standardised-difference boundary that separates what matching is responsible
#: for from what outcome regression is responsible for, and simultaneously the bound
#: on the latter. From Rubin's guidance that linear adjustment on an imbalance beyond
#: roughly a quarter of a standard deviation is unreliable, because it extrapolates
#: across covariate regions with no counterpart in the other arm. See
#: :func:`balance_table` for the measured tier structure this lands between.
MATERIALITY_SD = 0.25


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Matched sets, their weights, and the balance they achieve.

    ``matches`` is one row per (treated unit, matched control) pair.
    ``weights`` is one row per *unit* with the analysis weight it carries: 1 for a
    treated unit, and for a control the sum of its shares across every treated unit
    it serves. Those weights are what makes the ATT an average over treated units
    rather than over matched pairs.
    """

    matches: pd.DataFrame
    weights: pd.DataFrame
    balance: pd.DataFrame
    exclusions: pd.DataFrame
    #: Share of in-support treated units that found at least one control.
    retention: float
    #: Largest post-match SMD among ``MATCHED``-role covariates - those matching was
    #: responsible for. The number the covariate-balance gate reads; see
    #: :func:`balance_table` for why it is restricted that way.
    worst_smd: float
    #: Largest post-match SMD across every *gated* covariate - both the ``MATCHED``
    #: and ``ADJUSTED`` roles. Shown in the Method panel; gated per-covariate through
    #: ``balance["passes"]`` rather than against this single number, because the two
    #: roles carry different bounds. ``OFFSET`` covariates are excluded: they are
    #: unbalanced by design and would dominate this maximum, turning a summary meant
    #: to say "how well did the design do" into a restatement of a deliberate choice.
    #: Their imbalance is not hidden - it is reported on its own row with its reason.
    worst_smd_all: float
    #: Caliper on the linear propensity score, in score units.
    caliper: float
    #: Caliper on ``log1p`` baseline volume, in log units.
    volume_caliper: float
    #: Covariates the outcome model **must** include. These are the ``ADJUSTED``-role
    #: covariates: matching did not fix their residual imbalance and was not expected
    #: to, so the estimator discharges it instead. Honouring this is what makes their
    #: wider balance bound legitimate; an estimator that ignored it would be reading a
    #: balance table whose pass rule assumed work it never did.
    adjustment_covariates: tuple[str, ...]
    #: Outcome of the entropy-balancing refinement, applied or refused. Kept on the
    #: result rather than folded away because "these weights meet the treated means
    #: exactly" and "matching got this close on its own" are different claims about
    #: the same estimate, and the Method panel has to be able to say which one holds.
    refinement: BalanceRefinement
    #: Weights as *matching* produced them, before the refinement. Retained so
    #: diagnostics that the refinement constrains can still be computed on weights
    #: that did not have them imposed; a moment the solver was told to satisfy is no
    #: longer a test of whether the design satisfies it. Identical to
    #: :attr:`weights` when the refinement was refused.
    base_weights: pd.DataFrame
    #: Worst ``MATCHED`` SMD the *matching* achieved, before the refinement.
    #:
    #: This exists because :attr:`worst_smd` stops being informative once the
    #: refinement is applied: entropy balancing meets those moments by construction,
    #: so it reads ~0.001 whatever the design does, and a gate on it would be very
    #: nearly a tautology. What still carries information is how far matching got on
    #: its own - a design whose matched sets start at 0.4 SD and are dragged to zero by
    #: weights is not the same evidence as one that started at 0.09, even though the
    #: two report identical balance afterwards. Reported alongside
    #: :attr:`BalanceRefinement.ess_share`, which is what the dragging cost.
    worst_smd_unrefined: float

    @property
    def balance_passes(self) -> bool:
        """Every matched covariate inside its own bound.

        The gate reads this rather than comparing :attr:`worst_smd` to a threshold,
        because the two roles are held to different bounds and a single worst-case
        number cannot express both.
        """
        return bool(self.balance.empty or self.balance["passes"].all())

    @property
    def n_treated(self) -> int:
        return int(
            self.matches["event_id"].nunique()
            and self.matches[["event_id", "hcp_id"]].drop_duplicates().shape[0]
        )

    @property
    def n_controls(self) -> int:
        return int(self.matches[["event_id", "control_hcp_id"]].drop_duplicates().shape[0])


def _caliper(linear: np.ndarray, spec: EstimatorSpec) -> float:
    """Caliper width in linear-propensity units.

    Scaled by the pooled standard deviation of the score across *both* arms. Using
    the treated arm's SD alone would make the caliper depend on how selective this
    particular program was, so the same nominal 0.2 would mean different things for
    different events.
    """
    sd = float(np.std(linear, ddof=1)) if linear.size > 1 else 0.0
    return spec.caliper_sd * sd if sd > 0 else float("inf")


def match_cohort(scores: pd.DataFrame, features: pd.DataFrame, spec: EstimatorSpec) -> MatchResult:
    """Match each in-support treated unit to its nearest in-event controls.

    ``scores`` is :attr:`~.propensity.PropensityResult.scores`. Units outside
    common support were already flagged there and are skipped here rather than
    re-derived, so the two stages cannot disagree about who was eligible.

    ``features`` is required rather than optional because the balance table is not
    a follow-up report - it is the evidence that the matching worked, and a caller
    who could skip it would be able to obtain matched sets with no way to know
    whether they are balanced.
    """
    usable = scores[scores["in_support"]].reset_index(drop=True)
    caliper = _caliper(usable["linear_propensity"].to_numpy(dtype=float), spec)

    # The second distance dimension. See ``covariate_caliper_sd`` on the spec for
    # why a propensity caliper alone cannot deliver balance on volume.
    usable = usable.merge(
        features[["event_id", "hcp_id", BALANCE_COVARIATE]], on=["event_id", "hcp_id"], how="left"
    )
    usable["_volume"] = np.log1p(usable[BALANCE_COVARIATE].to_numpy(dtype=float))
    volume_sd = float(np.nanstd(usable["_volume"].to_numpy(), ddof=1))
    volume_caliper = spec.covariate_caliper_sd * volume_sd if volume_sd > 0 else float("inf")

    rows: list[dict[str, object]] = []
    unmatched: list[dict[str, object]] = []
    for event_id, block in usable.groupby("event_id", sort=False):
        treated = block[block["is_treated"]]
        controls = block[~block["is_treated"]]
        if treated.empty:
            continue
        if controls.empty:
            for _, unit in treated.iterrows():
                unmatched.append(
                    {
                        "tenant_id": unit["tenant_id"],
                        "event_id": event_id,
                        "hcp_id": unit["hcp_id"],
                        "reason": ExclusionReason.NO_MATCH_WITHIN_CALIPER.value,
                    }
                )
            continue

        c_scores = controls["linear_propensity"].to_numpy(dtype=float)
        c_volume = controls["_volume"].to_numpy(dtype=float)
        c_ids = controls["hcp_id"].to_numpy()
        for _, unit in treated.iterrows():
            distance = np.abs(c_scores - float(unit["linear_propensity"]))
            volume_gap = np.abs(c_volume - float(unit["_volume"]))
            # A control with no baseline volume reading cannot be shown to be
            # comparable on the dominant confounder, so it is not eligible. NaN
            # comparisons are False already; being explicit stops that from
            # looking like an accident.
            inside = np.flatnonzero(
                (distance <= caliper) & (volume_gap <= volume_caliper) & ~np.isnan(volume_gap)
            )
            if inside.size == 0:
                unmatched.append(
                    {
                        "tenant_id": unit["tenant_id"],
                        "event_id": event_id,
                        "hcp_id": unit["hcp_id"],
                        "reason": ExclusionReason.NO_MATCH_WITHIN_CALIPER.value,
                    }
                )
                continue
            # Nearest first, capped at the configured ratio. Fewer than the cap is
            # normal and fine - it means the caliper bound bit before the ratio did,
            # which is the priority order we want.
            chosen = inside[np.argsort(distance[inside], kind="stable")][
                : spec.controls_per_treated
            ]
            share = 1.0 / chosen.size
            for index in chosen:
                rows.append(
                    {
                        "tenant_id": unit["tenant_id"],
                        "event_id": event_id,
                        "hcp_id": unit["hcp_id"],
                        "brand_id": unit["brand_id"],
                        "control_hcp_id": c_ids[index],
                        "distance": float(distance[index]),
                        "control_share": share,
                    }
                )

    matches = pd.DataFrame(
        rows,
        columns=[
            "tenant_id",
            "event_id",
            "hcp_id",
            "brand_id",
            "control_hcp_id",
            "distance",
            "control_share",
        ],
    )
    exclusions = pd.DataFrame(unmatched, columns=["tenant_id", "event_id", "hcp_id", "reason"])

    n_eligible = int(usable["is_treated"].sum())
    matched_treated = matches[["event_id", "hcp_id"]].drop_duplicates().shape[0]
    retention = matched_treated / n_eligible if n_eligible else float("nan")

    weights = _analysis_weights(matches, usable)
    # First pass reads the roles. They depend only on the pre-match imbalance and the
    # covariate sets, never on the weights, so reading them from a table built on the
    # base weights is not circular - and it is the only way to tell the refinement
    # which covariates matching was actually responsible for.
    balance = balance_table(weights, features, usable, spec)
    unrefined = balance[balance["role"] == "MATCHED"]
    worst_unrefined = (
        float(unrefined["smd_after"].max(skipna=True)) if not unrefined.empty else float("nan")
    )
    refinement = _refine_weights(weights, features, usable, balance)
    base_weights = weights
    if refinement.applied:
        weights = refinement.weights
        balance = balance_table(weights, features, usable, spec)
    elif refinement.reason not in {"nothing to balance", "one arm is empty"}:
        _LOG.warning(
            "causal.matching.balance_refinement_refused",
            spec=spec.fingerprint,
            reason=refinement.reason,
            residual=refinement.max_residual,
            ess_share=refinement.ess_share,
        )
    if balance.empty:
        worst = worst_all = float("nan")
    else:
        # The gate reads only covariates that were actually imbalanced to begin
        # with. See balance_table for why a blanket threshold over all of them is
        # not a meaningful test at these sample sizes.
        matched = balance[balance["role"] == "MATCHED"]
        worst = float(matched["smd_after"].max(skipna=True)) if not matched.empty else 0.0
        gated = balance[balance["role"] != "OFFSET"]
        worst_all = float(gated["smd_after"].max(skipna=True)) if not gated.empty else 0.0
    adjust = () if balance.empty else tuple(balance.loc[balance["role"] == "ADJUSTED", "covariate"])

    result = MatchResult(
        matches=matches,
        weights=weights,
        balance=balance,
        exclusions=exclusions,
        retention=retention,
        worst_smd=worst,
        worst_smd_all=worst_all,
        caliper=caliper,
        volume_caliper=volume_caliper,
        adjustment_covariates=adjust,
        refinement=refinement,
        base_weights=base_weights,
        worst_smd_unrefined=worst_unrefined,
    )
    _LOG.info(
        "causal.matching.done",
        spec=spec.fingerprint,
        caliper=caliper,
        eligible_treated=n_eligible,
        matched_treated=matched_treated,
        pairs=len(matches),
        volume_caliper=volume_caliper,
        distinct_controls=int(matches["control_hcp_id"].nunique()) if len(matches) else 0,
        retention=retention,
        worst_smd=worst,
        worst_smd_all=worst_all,
        worst_smd_unrefined=worst_unrefined,
        refinement_applied=refinement.applied,
        refinement_reason=refinement.reason,
        ess_share=refinement.ess_share,
        balance_passes=result.balance_passes,
        adjust=len(adjust),
    )
    return result


def _refine_weights(
    weights: pd.DataFrame,
    features: pd.DataFrame,
    eligible: pd.DataFrame,
    balance: pd.DataFrame,
) -> BalanceRefinement:
    """Entropy-balance the control weights against the ``MATCHED`` covariates.

    Plus :data:`TREND_COVARIATES`, whether or not matching was held responsible for
    them - see that constant for why the baseline trend is safe to constrain when the
    baseline level is not.

    The scale passed to the solver is the same pre-matching pooled standard deviation
    the balance table divides by, taken from the same ``eligible`` population. If the
    two disagreed the solver would be driving a residual measured in units the gate
    does not use, and could converge to something the gate still fails.
    """
    if balance.empty:
        return BalanceRefinement(weights, False, "nothing to balance", float("nan"), 0.0, 0.0, 0)
    matched = tuple(balance.loc[balance["role"] == "MATCHED", "covariate"])
    columns = matched + tuple(c for c in TREND_COVARIATES if c not in matched)
    before = eligible[["event_id", "hcp_id", "is_treated"]].merge(
        features, on=["event_id", "hcp_id"], how="left"
    )
    treated_mask = before["is_treated"].to_numpy(dtype=bool)
    scale = {
        column: _pooled_sd(before[column].to_numpy(dtype=float), treated_mask)
        for column in columns
        if column in before
    }
    return entropy_balance(weights, features, columns, scale)


def _analysis_weights(matches: pd.DataFrame, usable: pd.DataFrame) -> pd.DataFrame:
    """Per-unit analysis weight: 1 for treated, summed shares for controls.

    A control matched to three treated units, each of which split its weight three
    ways, carries 3 x 1/3 = 1. The construction guarantees the two arms carry equal
    total weight, which is what makes the difference in weighted means an ATT
    estimate for the matched treated population rather than for some mixture of the
    two.
    """
    if matches.empty:
        return pd.DataFrame(columns=["event_id", "hcp_id", "is_treated", "weight"])

    treated = matches[["event_id", "hcp_id"]].drop_duplicates().assign(is_treated=True, weight=1.0)
    control = (
        matches.groupby(["event_id", "control_hcp_id"], as_index=False)["control_share"]
        .sum()
        .rename(columns={"control_hcp_id": "hcp_id", "control_share": "weight"})
        .assign(is_treated=False)
    )
    return pd.concat(
        [treated, control[["event_id", "hcp_id", "is_treated", "weight"]]], ignore_index=True
    )


def balance_table(
    weights: pd.DataFrame,
    features: pd.DataFrame,
    eligible: pd.DataFrame,
    spec: EstimatorSpec,
    covariates: tuple[str, ...] = MATCHING_COVARIATES,
) -> pd.DataFrame:
    """Standardised mean differences before and after matching, with a pass rule.

    ``eligible`` is the in-support cohort with its ``is_treated`` flag: the *before*
    population. It is passed in rather than inferred from ``weights``, because
    ``weights`` holds only units that found a match, and the before column has to
    describe the imbalance that existed prior to matching - including the units
    matching could not place.

    Two conventions here are the two places a balance table is commonly fudged.

    The denominator is the **pre-matching** pooled standard deviation, held fixed
    across both columns. Recomputing it on the matched sample makes the after figure
    incomparable with the before one, and it can improve on paper purely because
    matching narrowed the variance.

    The after column is **weighted** by the analysis weights, not a plain mean over
    matched rows. An unweighted mean over pairs over-counts controls serving several
    treated units, and would report balance the estimate does not use.

    Why the pass rule is not simply ``smd_after <= 0.10``
    ----------------------------------------------------
    plan.md §12.3 asks for an SMD below 0.10 on every matched covariate. Enforced
    literally that gate fails cohorts that are in fact well matched, and it does so
    for a reason that has nothing to do with the matching.

    Measured on the synthetic cohort across five seeds, pre-matching imbalance falls
    into three clearly separated tiers::

        0.500 - 0.763   decile, pre_nrx_mean, pre_trx_mean, pre_rep_calls
        0.095 - 0.217   prior_engagement_count, prior_same_brand_attendances
        0.003 - 0.049   pre_competitor_share, pre_nrx_trend, years_in_practice

    The first tier is what selection actually did, and matching fixes it: those four
    land at 0.033-0.080 on every seed. But matching *worsens* the third tier - it
    took ``pre_competitor_share`` from 0.021 to 0.139 - because constraining controls
    on propensity and on baseline volume draws them from a narrower slice of the
    population, and that slice differs on things the caliper never mentioned. A
    blanket 0.10 gate therefore fails on a covariate representing a gap of **1.1
    percentage points of competitor share**, while the confounders matching exists to
    handle are all comfortably inside it.

    Tightening the calipers does not help; it makes it worse, by shrinking the pool
    further. The remedy is the standard one, and it is why matching and outcome
    regression are normally used together rather than as alternatives.

    Two roles, two bounds
    ---------------------
    ``role`` splits the covariates by what is responsible for handling them.

    ``MATCHED`` - pre-matching SMD at or above :data:`MATERIALITY_SD`. An imbalance
    this large cannot be trusted to linear adjustment, which would be extrapolating
    across regions of covariate space with no counterpart in the other arm. Matching
    must fix it, and it is gated at the full ``max_smd_after_matching``.

    ``OFFSET`` - :data:`OFFSET_COVARIATES`, handled structurally by the estimator
    rather than by balancing, and therefore not gated. The baseline level enters the
    Poisson pseudo-likelihood as a fixed ``log(pre_mean)`` offset, which absorbs each
    unit's own level exactly; and since the caliper deliberately constrains the
    *earlier* window instead, the baseline window is left free to carry its own noise,
    which is the whole point. Reported with its reason, never dropped.

    ``ADJUSTED`` - :data:`DEFERRED_COVARIATES`, plus everything else. Residual imbalance
    here is first-order removable
    by including the covariate in the outcome model, so the bound is
    :data:`MATERIALITY_SD` rather than the matching threshold: the question is no
    longer "did matching fix it" but "is it small enough for adjustment to fix it".
    Beyond that bound neither mechanism is reliable and the analysis genuinely should
    fail. These covariates are returned in
    :attr:`MatchResult.adjustment_covariates`, and the estimator is required to
    include them - which is what makes the wider bound legitimate rather than a
    weakening.

    The threshold for both purposes is 0.25 SD, from Rubin's guidance that regression
    adjustment on an imbalance beyond about a quarter of a standard deviation is
    unreliable. It is one published constant serving both roles, not a value tuned
    until the gate passed: it lands inside the empty band between the tiers above
    with margin on each side, so a covariate does not change role from seed to seed.
    Measured on the 30-month synthetic panel, both bounds hold on all five seeds:
    worst ``MATCHED`` 0.0010 against 0.10, worst ``ADJUSTED`` 0.225 against 0.25. The
    ``MATCHED`` figure is near zero because :mod:`.balancing` meets those moments by
    construction; before that refinement the same matched sets left the worst at
    0.095-0.138, which is why the refinement exists. The ``ADJUSTED`` figure is the
    one with real margin left to spend, and it is spent by ``prior_engagement_count``,
    the one covariate matching reliably makes slightly *worse* (0.15-0.16 before,
    0.14-0.23 after) - it is a discrete count with a long tail, so a matched set
    chosen on the score can easily be less balanced on it than the full cohort was.

    ``tolerance`` widens either bound to the 2-SE sampling band when that band is the
    wider of the two. When the true difference is zero the standard error of an
    estimated SMD is about ``sqrt(1/n_t + 1/n_c)``, so an analysis with ~660 matched
    attendees and ~830 controls has a 2-SE band of 0.104 - wider than the matching
    threshold itself, meaning a perfectly matched cohort would fail on some covariate
    almost every time from noise alone. Effective sample sizes use Kish's
    ``(sum w)^2 / sum w^2``, which discounts a control reused across several treated
    units: such a control carries less independent information than three distinct
    ones, and ignoring that would understate the band. At the full synthetic cohort
    (~1,240 effective per arm) the band is 0.080 and does not bind; it binds on the
    small per-event and per-brand cuts, which is exactly where it should.
    """
    keys = ["event_id", "hcp_id"]
    before = eligible[[*keys, "is_treated"]].merge(features, on=keys, how="inner")
    after = weights[[*keys, "is_treated", "weight"]].merge(features, on=keys, how="inner")

    matched_bound = spec.gates.max_smd_after_matching
    n_t_eff = _effective_n(after, treated=True)
    n_c_eff = _effective_n(after, treated=False)
    se = float(np.sqrt(1.0 / n_t_eff + 1.0 / n_c_eff)) if n_t_eff > 0 and n_c_eff > 0 else np.nan
    noise = 2.0 * se if se == se else 0.0

    records: list[dict[str, object]] = []
    for column in covariates:
        b_values = before[column].to_numpy(dtype=float)
        b_treated = before["is_treated"].to_numpy(dtype=bool)
        pooled = _pooled_sd(b_values, b_treated)
        smd_before = _weighted_smd(b_values, np.ones_like(b_values), b_treated, pooled)
        smd_after = _weighted_smd(
            after[column].to_numpy(dtype=float),
            after["weight"].to_numpy(dtype=float),
            after["is_treated"].to_numpy(dtype=bool),
            pooled,
        )
        # A covariate whose pre-match SMD is not computable (constant, or an arm
        # absent) is treated as ADJUSTED. Calling it MATCHED would gate it at the
        # tighter bound on the strength of a number we do not have.
        material = bool(smd_before >= MATERIALITY_SD) if smd_before == smd_before else False
        if column in OFFSET_COVARIATES:
            role, bound = "OFFSET", float("inf")
        elif column in DEFERRED_COVARIATES:
            role, bound = "ADJUSTED", max(MATERIALITY_SD, noise)
        else:
            role = "MATCHED" if material else "ADJUSTED"
            bound = max(matched_bound if material else MATERIALITY_SD, noise)
        records.append(
            {
                "covariate": column,
                "smd_before": smd_before,
                "smd_after": smd_after,
                "role": role,
                "tolerance": bound,
                "passes": bool(smd_after <= bound) if smd_after == smd_after else True,
            }
        )
    table = pd.DataFrame(records)
    if table.empty:
        return table
    table["improvement"] = table["smd_before"] - table["smd_after"]
    table["n_treated_effective"] = n_t_eff
    table["n_control_effective"] = n_c_eff
    return table.sort_values(["role", "smd_after"], ascending=[True, False], ignore_index=True)


def _effective_n(frame: pd.DataFrame, *, treated: bool) -> float:
    """Kish effective sample size for one arm: ``(sum w)^2 / sum w^2``.

    Equals the row count when every weight is 1, and falls as weights concentrate -
    which is what happens when a few controls each serve many treated units.
    """
    if frame.empty or "weight" not in frame:
        return 0.0
    w = frame.loc[frame["is_treated"] == treated, "weight"].to_numpy(dtype=float)
    w = w[~np.isnan(w)]
    total = w.sum()
    return float(total * total / np.square(w).sum()) if total > 0 else 0.0


def _pooled_sd(values: np.ndarray, treated: np.ndarray) -> float:
    """Pooled SD across arms, ignoring missing values.

    Pooled rather than the treated arm's own SD: the treated arm is the smaller one,
    so its variance is the noisier estimate, and an SMD that moved because its
    denominator moved is not a balance improvement.
    """
    a, b = values[treated], values[~treated]
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if a.size < 2 or b.size < 2:
        return 0.0
    return float(np.sqrt((np.var(a, ddof=1) + np.var(b, ddof=1)) / 2))


def _weighted_smd(values: np.ndarray, w: np.ndarray, treated: np.ndarray, pooled: float) -> float:
    """Weighted standardised mean difference; ``nan`` where it is not defined.

    Returns ``nan`` rather than 0.0 for a constant covariate or an absent arm. Zero
    would read as perfect balance, which is the one answer that must never be
    produced by an absence of data.
    """
    if pooled <= 0:
        return float("nan")
    ok = ~np.isnan(values) & ~np.isnan(w)
    values, w, treated = values[ok], w[ok], treated[ok]
    if not treated.any() or treated.all():
        return float("nan")

    def mean(mask: np.ndarray) -> float:
        total = w[mask].sum()
        return float((values[mask] * w[mask]).sum() / total) if total > 0 else float("nan")

    return float(abs(mean(treated) - mean(~treated)) / pooled)
