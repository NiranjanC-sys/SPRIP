"""Every parameter of the synthetic data-generating process, in one place.

Why this file exists at all
---------------------------
The entire causal pipeline is validated against data produced here. If a
coefficient is buried three call frames deep inside a generator function, then
"what exactly is the confounding structure?" becomes an archaeology exercise
instead of a code review. So: **no magic numbers anywhere else in this
package.** Every coefficient below carries a comment explaining its business
meaning, because the person who has to defend this DGP to a statistician is the
person reading this file.

Two profiles, one DGP
---------------------
``smoke`` and ``full`` differ only in *volume* parameters (counts, months,
panel density). The behavioural coefficients - selection betas, effect
hierarchy, over-dispersion, imperfection rates - are shared, so a green
``smoke`` run is genuine evidence about the ``full`` dataset rather than
evidence about a different model.

Row minimums come from ``docs/PLAN_REVIEW.md`` F-2, which resolves the
self-contradiction in ``plan.md`` §11 (5,000 events *and* "250-300 historical
events"; 5,000 events with 5,000 attendance rows implies one attendee per
event, which makes per-event estimation impossible by construction).

Deliberate deviations from the brief, and why
---------------------------------------------
1. **The treatment effect is additive on the count scale, not the log scale.**
   ``plan.md`` §11 writes ``log lambda = ... + treatment_effect``, but the same
   section states the magnitude as "0.35-1.40 incremental NRx per attendee per
   month" (a count) and defines the stored truth as the effect *integrated over
   the post months times the attendee count* (an additive count). A DiD
   estimator on levels targets an additive ATT. Making the DGP multiplicative
   while storing an additive truth would guarantee the recovery test fails for a
   definitional reason rather than an estimator reason - precisely the failure
   mode the brief warns about. See ``outcomes.py`` for the full argument.

2. **Mean invitations per event is 50-55, not 40.** ``plan.md`` says "NegBin
   around 40". PLAN_REVIEW F-2 simultaneously requires >=62,000 verified
   attendance rows across ~4,300 completed events (>=14.4 attendees/event) at a
   26-32% attendance rate, which forces >=48 invitations per completed event.
   40 is arithmetically impossible against the row minimums; the minimums win.

3. **The selection model carries one term the brief does not list:** a
   satiation penalty on HCPs who attended a same-brand program in the previous
   ``satiation_window_months``. It is a pre-event observable (the HCP's own
   attendance history), so it introduces no leakage, and it is the only
   available lever on overlapping exposure - see deviation 4.

4. **Overlapping exposure reaches the brief's ~6%, but only after the HCP
   universe was enlarged.** An earlier revision of this file recorded that ~6%
   was arithmetically unreachable and that the only lever,
   ``beta_recent_attendance_satiation``, destroyed the confounding when pushed
   hard enough to get there. That conclusion was measured, and it was wrong -
   because it held the wrong parameter fixed. Both claims were tested against
   ``n_hcps_per_tenant`` instead, and the relationship is sharp
   (``scripts/devtools/sweep_overlap.py``, smoke, seed 20260819)::

       hcps/tenant   overlap   verified   attendees/event   usable/event
             400      39.9%      2,511          13.9              8.4
             800      17.8%      2,515          14.0             11.5
           1,200       5.9%      2,510          13.9             13.1
           2,000       2.6%      2,517          14.0             13.6
           3,200       1.4%      2,516          14.0             13.8

   ``full`` needed the same treatment and confirms the mechanism at four times
   the event volume - at its original 5,200 it sat at 30.2%::

       hcps/tenant   overlap   verified   attendees/event   usable/event
           5,200      30.2%     68,634         16.0             11.1
           9,000       7.2%     67,352         15.7             14.5
          12,000       4.9%     67,300         15.6             14.9
          14,000       4.5%     67,282         15.6             14.9
          20,000       3.1%     67,194         15.6             15.1

   Contamination is a density: a same-brand invitation lands in an HCP's 90-day
   window at a rate proportional to events x invitees x attendance rate divided
   by the size of the universe those invitations are drawn from. Only the
   denominator was ever free. The curve is steeper than 1/n, because a larger
   pool leaves the invitation scheduler enough un-cooled candidates to actually
   honour its per-HCP-brand cooldown instead of running out of eligible
   prescribers and seating repeat attendees. The verified-attendance count is flat across the
   whole sweep, so enlarging the universe costs nothing that the row minimums
   care about - it does not trade against anything - and it *raises* the usable
   treated cohort by 56% at the same event volume, because fewer attendances are
   excluded.

   It is also the more realistic parameter by a wide margin. 400 prescribers per
   customer was never a defensible figure for a therapy area running hundreds of
   speaker programs a year; a real target universe is tens of thousands, and
   1,200 is still conservative. The satiation coefficient stays at -1.75, and
   the pre-period SMD *improves* to ~0.75 rather than collapsing to 0.014.

   The lesson is recorded here because it generalises: the earlier table
   correctly measured a trade-off that existed only inside a parameterisation
   nobody had questioned. ``scripts/devtools/dgp_diagnostics.py`` now measures
   all four asserted properties together, over several seeds, so a claim of this
   kind cannot survive on one number again.

5. **The field force is modelled as targeting expected volume, not realised
   volume.** Selecting invitees on the *realised* six-month prescribing count
   means selecting partly on that window's noise draw, and whoever is picked for
   running hot then reverts toward their own mean in the post window while the
   controls - not picked that way - do not. That is a parallel-trends violation
   built into the data, and it measured large enough to flip the sign of the
   estimate (-1.0 to -1.8x the truth). Real targeting runs off vendor-supplied
   deciles and potential scores, which are smoothed estimates of the systematic
   level, so the fix is also the more faithful model. See the comment at
   ``pre_level`` in ``outcomes.py``.

6. **That expected volume deliberately excludes the HCP's own prior treatment
   effect.** With the decaying tail of an earlier program left in the targeting
   score, every repeat attendee is selected at a locally elevated point on a
   curve already on its way down. Measured, this cancelled the entire effect: an
   expected +0.40 NRx per attendee-month came out at -0.10. Prescriber potential
   is a property of the practice, and ``lam_hb`` in ``outcomes.py`` keeps it one.

   5 and 6 were both masked by the 40% contamination that deviation 4 removed.
   Fixing overlap is what exposed them, which is the argument for gating all
   four properties at once rather than one at a time.

7. **A promotional halo surrounds every invited program** (``ContextParams``
   ``halo_*``). Once contamination was fixed, nothing in the DGP made a naive
   pre/post overstate the truth: rep activity had no event-time structure at all,
   and the measured naive/true ratio wandered between 0.0 and 4.7 on the seed
   alone, because no mechanism was driving it. plan.md §24.5 requires that story
   to be tellable. The halo attaches to the *invitation* rather than to
   attendance, which makes it a pre-treatment observable shared with the invited
   non-attendees the controls are drawn from - so it inflates the naive number
   and cancels in a matched comparison. Attaching it to attendance instead would
   make the truth unrecoverable in principle rather than merely hard, which is
   not a property worth simulating.

A constraint this DGP places on the estimator
---------------------------------------------
Parallel trends holds in **log** NRx, not in levels, and this is a property of
the world rather than an artefact. Volume is multiplicative (``exp(linear)``) and
attendees are selected to a higher level by design, so any movement common to
both groups - the halo, access, competitor pressure, seasonality - scales with
each unit's own level and produces a larger *absolute* change for attendees.
Measured on smoke, the pre-period trend gap is 0.001-0.019 log points but -0.26
to +2.72 times the effect in raw levels.

A multiplicative outcome, selection on level, and additive parallel trends cannot
all hold; the first two are the realistic ones. So M2 must not difference raw NRx
across groups sitting at different baselines. Working in logs, or differencing
within strata of baseline volume - where treated and control share a level, so a
common multiplicative shock is the same absolute amount - both discharge it, and
the pre-period matching plan.md §12.2 already mandates is what produces those
strata. The stored truth being additive in NRx while the confounding is
multiplicative is the hard case on purpose: it is why the estimator has to
condition on baseline rather than merely adjust for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Final, Literal

__all__ = [
    "FULL",
    "GENERATOR_VERSION",
    "PANEL_END_MONTH",
    "PROFILES",
    "SMOKE",
    "ContextParams",
    "CostParams",
    "EffectParams",
    "EventDesignParams",
    "HcpPopulationParams",
    "ImperfectionRates",
    "LatentParams",
    "OutcomeParams",
    "ProfileName",
    "SelectionParams",
    "SourceFileParams",
    "SyntheticProfile",
    "VolumeTargets",
    "get_profile",
]

ProfileName = Literal["smoke", "full"]

#: Bumped whenever a change alters generated values. The manifest records it so a
#: stored dataset can be traced to the code that produced it (plan.md §14).
#:
#: 2.0.0 - enlarged the HCP universe, moved invitation targeting onto expected
#: rather than realised prescribing volume, excluded prior treatment effects from
#: the targeting score, and added the promotional halo around invited programs.
#: See deviations 4-7 in the module docstring. Every value in every frame differs
#: from 1.0.0, so any stored 1.0.0 dataset must be regenerated rather than
#: appended to.
GENERATOR_VERSION: Final[str] = "2.0.0"

#: The panel always ends on this month. Hard-coded rather than derived from the
#: wall clock: plan.md §11 requires "seed scripts must be deterministic and safe
#: to rerun", and a clock-derived window silently changes every dataset the day
#: the month rolls over.
PANEL_END_MONTH: Final[date] = date(2026, 6, 1)


# ===========================================================================
# Outcome process - plan.md §11 "over-dispersed count outcomes with market
# trend, seasonality, access, competitor pressure"
# ===========================================================================


@dataclass(frozen=True, slots=True)
class OutcomeParams:
    """Coefficients of ``log lambda[h,b,t]`` and the count noise on top of it.

    The linear predictor is (plan.md §11)::

        log lambda = a_h + b_brand + b_product
                   + trend_b * (t / 12)
                   + s(t)
                   + g1 * access_index[b, region(h), t]
                   - g2 * competitor_index[b, region(h), t]
                   + g3 * log1p(rep_calls[h, t])
                   + g4 * latent_affinity[h]

    and the treatment effect is added to ``lambda`` afterwards, on the count
    scale (see the module docstring).
    """

    # --- HCP intercept ----------------------------------------------------
    #: Grand mean of log lambda. exp(1.15) ~ 3.2 NRx per product-month, which is
    #: a plausible specialist volume for a single SKU and leaves room for a
    #: 0.3-1.4 NRx uplift to be a 10-40% relative effect - big enough to measure,
    #: small enough that a naive before/after is not obviously right.
    intercept: float = 1.15
    #: Loading of log(latent_opportunity) onto the HCP intercept. This is the
    #: dominant confounder: it drives baseline volume *and* attendance.
    beta_opportunity_on_intercept: float = 0.92
    #: Between-brand level spread (sd of a Normal draw), on the log scale.
    brand_level_sd: float = 0.26
    #: Between-product (within-brand) level spread. Second and third SKUs of a
    #: brand carry less volume than the flagship formulation.
    product_level_sd: float = 0.20
    #: Mean log-scale offset applied to non-flagship products of a brand.
    non_flagship_product_offset: float = -0.35

    # --- secular trend and seasonality ------------------------------------
    #: Per-brand annual log-growth, drawn Normal(mean, sd). Some brands are
    #: launching (positive), some are being genericised (negative).
    brand_trend_mean: float = 0.06
    brand_trend_sd: float = 0.13
    #: s(t) = seasonality_sin_amp * sin(2*pi*t/12) + seasonality_cos_amp * cos(4*pi*t/12)
    #: Exactly the form specified in plan.md §11.
    seasonality_sin_amp: float = 0.12
    seasonality_cos_amp: float = 0.05

    # --- market context ---------------------------------------------------
    #: g1 - payer access lifts prescribing. A 0.30 swing in access_index moves
    #: lambda by exp(0.55*0.30) ~ +17%.
    g1_access: float = 0.55
    #: g2 - competitor pressure suppresses it (enters with a minus sign).
    g2_competitor: float = 0.45
    #: g3 - rep calls. log1p so the tenth call adds far less than the first.
    #: rep_calls also correlates with latent_opportunity, so this is a *second*
    #: confounding path, and one the propensity model can actually observe.
    g3_rep_calls: float = 0.22
    #: g4 - pre-existing brand affinity. Latent, therefore unobservable to the
    #: propensity model: this is the residual confounding the sensitivity
    #: analysis is supposed to bound.
    g4_affinity: float = 0.60

    # --- count noise ------------------------------------------------------
    #: NegBin dispersion phi. Var = mu + mu^2/phi, so var/mean = 1 + mu/phi.
    #: At mu ~ 3.2 that is ~3.0 - comfortably over-dispersed, which is what
    #: makes a Poisson-assuming estimator visibly wrong.
    dispersion_phi: float = 1.6
    #: Refill intensity: refills ~ Poisson(refill_rate * rolling_mean(NRx, 3)).
    #: TRx = NRx + refills, so TRx/NRx lands near 2.9 - a chronic-therapy shape.
    refill_rate: float = 1.9
    #: Competitor TRx runs above own-brand TRx in a contested market.
    competitor_log_offset: float = 0.42
    #: How strongly competitor_trx tracks the competitor index.
    competitor_index_loading: float = 0.80
    #: Competitor counts are noisier (aggregated across several molecules).
    competitor_dispersion_phi: float = 2.4

    # --- numerical guards -------------------------------------------------
    #: lambda floor. Only binds for negative-effect events on already-tiny
    #: baselines; the generator asserts total clipping loss stays negligible so
    #: the stored truth equals the realised truth.
    lambda_floor: float = 0.01
    #: lambda ceiling, so a 4-sigma latent_opportunity draw cannot produce an
    #: implausible 400-script month.
    lambda_ceiling: float = 90.0


# ===========================================================================
# Latent HCP attributes - plan.md §11 "latent opportunity, affinity, prior
# engagement ... influence attendance"
# ===========================================================================


@dataclass(frozen=True, slots=True)
class LatentParams:
    """The four hidden HCP attributes. Written only to ``ground_truth/``."""

    #: latent_opportunity ~ LogNormal(mu, sigma) - patient panel size /
    #: prescribing potential. sigma=0.55 gives a 90:10 ratio of ~4.1x, which
    #: matches the decile spread commissioners see in real prescriber data.
    opportunity_log_mu: float = 0.0
    opportunity_log_sigma: float = 0.55
    #: latent_affinity ~ Beta(2, 5) on [0, 1] - pre-existing brand preference.
    #: Right-skewed: most HCPs are indifferent, a minority are already advocates.
    affinity_beta_a: float = 2.0
    affinity_beta_b: float = 5.0
    #: latent_access_sensitivity ~ Normal(0, 1) - how much a formulary change
    #: moves this prescriber. Modulates the access term per HCP.
    access_sensitivity_mu: float = 0.0
    access_sensitivity_sigma: float = 1.0
    #: prior_engagement_count ~ Poisson(1.2) - programs attended before the
    #: observation window opens. An observable proxy for the latent traits.
    prior_engagement_lambda: float = 1.2
    #: Per-HCP modulation of g1_access by latent_access_sensitivity.
    access_sensitivity_loading: float = 0.18


# ===========================================================================
# HCP population shape
# ===========================================================================


@dataclass(frozen=True, slots=True)
class HcpPopulationParams:
    """How the prescriber universe is composed.

    Nothing here is a causal coefficient; these are the population weights that
    decide *who exists*. They live in config anyway so that "why are 41% of the
    universe cardiologists?" has a one-line answer.
    """

    #: Weight of each practice type. Community practice dominates real
    #: speaker-program target lists.
    practice_type_weights: dict[str, float] = field(
        default_factory=lambda: {
            "COMMUNITY": 0.52,
            "HOSPITAL": 0.24,
            "ACADEMIC": 0.13,
            "INTEGRATED_DELIVERY_NETWORK": 0.08,
            "TELEHEALTH": 0.03,
        }
    )
    #: Segment is assigned by *decile of latent_opportunity*, not drawn
    #: independently - segmentation in the field is explicitly a volume
    #: exercise, and this keeps segment a usable observable proxy for the
    #: latent confounder.
    segment_decile_cuts: tuple[float, ...] = (0.60, 0.85, 0.96)
    segment_labels: tuple[str, ...] = ("TIER_4", "TIER_3", "TIER_2", "TIER_1")
    #: Share of HCPs whose region is drawn from a skewed rather than uniform
    #: distribution: real target lists cluster around metro areas.
    region_concentration: float = 1.35
    #: Probability an HCP has a usable NPI-style national identifier in the CRM
    #: extract. The rest must be matched on name + state, which is what makes
    #: the crosswalk interesting (plan.md §10.4).
    has_national_id_rate: float = 0.93
    #: Years in practice ~ Gamma(shape, scale), clipped. Used as a benign
    #: covariate so the propensity model has something that is *not* a
    #: confounder to discard.
    years_in_practice_shape: float = 4.0
    years_in_practice_scale: float = 4.5
    years_in_practice_max: float = 45.0


# ===========================================================================
# Event and campaign design
# ===========================================================================


@dataclass(frozen=True, slots=True)
class EventDesignParams:
    """The observable design of a program: format, size, speaker, timing."""

    #: Format mix across the portfolio. In-person still dominates spend, but the
    #: virtual tail has to be big enough to estimate a format effect on.
    format_weights: dict[str, float] = field(
        default_factory=lambda: {
            "IN_PERSON": 0.44,
            "VIRTUAL": 0.24,
            "ROUNDTABLE": 0.16,
            "HYBRID": 0.11,
            "ON_DEMAND": 0.05,
        }
    )
    speaker_tier_weights: dict[str, float] = field(
        default_factory=lambda: {
            "LOCAL_SPEAKER": 0.58,
            "REGIONAL_EXPERT": 0.31,
            "NATIONAL_KOL": 0.11,
        }
    )
    #: planned_attendees = round(invited * planned_ratio) with lognormal noise;
    #: planners over-book because they know attendance is ~30%.
    planned_attendee_ratio: float = 0.42
    planned_attendee_noise_sigma: float = 0.12
    planned_attendee_min: int = 6
    #: Events cluster in the working months; nobody runs a dinner programme in
    #: late December. Multiplier on the per-month event placement weight,
    #: indexed by calendar month 1..12.
    month_placement_weights: dict[int, float] = field(
        default_factory=lambda: {
            1: 0.85,
            2: 1.05,
            3: 1.20,
            4: 1.15,
            5: 1.15,
            6: 1.00,
            7: 0.70,
            8: 0.70,
            9: 1.25,
            10: 1.30,
            11: 1.15,
            12: 0.55,
        }
    )
    #: Day-of-month spread for the event date within its month.
    event_day_lo: int = 2
    event_day_hi: int = 27
    #: A campaign is a brand x quarter-ish push; events inherit its brand and
    #: target specialties. Share of campaign-target specialties out of all.
    campaign_target_specialty_share: float = 0.45
    #: Lead time from invitation to event, days.
    invitation_lead_days_lo: int = 10
    invitation_lead_days_hi: int = 45

    # --- who gets invited --------------------------------------------------
    #: Log-weights for the Gumbel-top-k invitation draw. Invitation is a
    #: *commercial* decision made before the event, so it may depend only on
    #: things the field force knows: territory, specialty, segment, and who they
    #: have engaged before. It must not depend on the outcome, or the invited
    #: population itself would be post-treatment-selected.
    invite_w_same_region: float = 1.60
    invite_w_topic_fit: float = 0.90
    invite_w_opportunity: float = 0.55
    invite_w_prior_engagement: float = 0.35
    #: Reps invite prescribers they already track. This keeps outcome coverage
    #: high enough that most events clear the coverage gate for a real reason.
    invite_w_in_brand_panel: float = 1.20
    #: Penalty per invitation already received in the trailing cooldown window.
    #: Without it the same 200 high-opportunity HCPs absorb every invitation and
    #: overlapping exposure explodes.
    invite_cooldown_penalty: float = 1.30
    invite_cooldown_days: int = 120
    #: A *brand-specific* cooldown, much stronger and much longer. Speaker
    #: program compliance policies cap how often the same prescriber can be
    #: engaged on the same brand, and without modelling that cap the mandated
    #: invitation density puts ~48% of attendees inside another program's
    #: 90-day window - which would strip half the treated cohort out for
    #: ExclusionReason.OVERLAPPING_EXPOSURE and leave nothing to estimate on.
    #: Large enough to act as a hard exclusion under Gumbel-top-k, but finite,
    #: so that if a brand's remaining candidate pool is too small to fill the
    #: list the least-recently-engaged blocked HCPs are used rather than the
    #: draw failing. 100 days is the operative cap: a second program inside the
    #: 90-day outcome window is what makes an event un-attributable.
    invite_brand_cooldown_penalty: float = 25.0
    invite_brand_cooldown_days: int = 100
    #: Share of events that ignore the brand cap - regional blitzes, vendor-run
    #: series, and the plain fact that policies get exceptions. This is the knob
    #: that lands overlapping exposure near the ~6% plan.md §11 asks for; at the
    #: mandated invitation density (>=12 invitations per HCP over the window) an
    #: uncapped draw produces ~48%, which would gut the treated cohort.
    invite_cooldown_exception_rate: float = 0.10
    #: Channel mix for the invitation record.
    invitation_channel_weights: dict[str, float] = field(
        default_factory=lambda: {
            "REP": 0.46,
            "EMAIL": 0.34,
            "PORTAL": 0.13,
            "PHONE": 0.05,
            "OTHER": 0.02,
        }
    )


# ===========================================================================
# Attendance selection - plan.md §11 "simulate intentional selection bias"
# ===========================================================================


@dataclass(frozen=True, slots=True)
class SelectionParams:
    """logit P(verified attendance | invited).

    Coefficients are on standardised (z-scored) features, so they are directly
    comparable: 0.80 on ``z(latent_opportunity)`` means a one-sd higher
    prescribing potential multiplies the attendance odds by e^0.80 = 2.2.

    The first two terms are the confounders that matching **cannot** fix,
    because they are latent. The third is the confounder matching **can** fix,
    because pre-period Rx is observable. That asymmetry is the entire point of
    the demo: propensity matching closes the observable path and the sensitivity
    analysis has to bound the latent one.
    """

    # --- confounders that also drive the outcome ---------------------------
    beta_latent_opportunity: float = 0.80
    beta_latent_affinity: float = 0.65
    #: Observable pre-event Rx *level* - the mean of the HCP's own NRx over
    #: months [m-6, m-1]. Matching can and must correct this one, and it is
    #: the term that produces most of the asserted pre-period SMD.
    #: Deliberately the level and not the six-month slope: see deviation 5.
    beta_pre6m_nrx_level: float = 0.55
    # --- design and engagement --------------------------------------------
    #: topic_fit in [0, 1]: does this topic match the HCP's specialty?
    beta_topic_fit: float = 0.40
    beta_prior_engagement: float = 0.30
    beta_rep_calls_pre3m: float = 0.25
    # --- frictions (negative) ---------------------------------------------
    #: travel_friction in [0, 1]: IN_PERSON in a remote region is ~1.0,
    #: VIRTUAL is 0.0. Enters with a minus sign.
    beta_travel_friction: float = -0.70
    #: Competing demands on the same calendar month.
    beta_competing_events: float = -0.20
    #: Not in plan.md §11's list - see module docstring deviation 3. An HCP who
    #: attended a same-brand program within the previous
    #: ``satiation_window_months`` is materially less likely to attend another:
    #: invitation lists are built to spread reach, and a prescriber who came last
    #: month is a poorer use of the next seat than one who has not.
    #:
    #: This was once believed to be the only lever on overlapping exposure, and
    #: pushing it to -5.50 does drive overlap to the brief's 6% - while flattening
    #: the pre-period SMD to 0.01, because frequent attenders are exactly the
    #: high-opportunity prescribers selection is supposed to favour. That trade-off
    #: is real but it was never the binding constraint; the HCP universe size was
    #: (deviation 4). At 1,200 HCPs/tenant this coefficient sits at -1.75 with
    #: overlap at ~6% *and* SMD at ~0.75, so nothing has to be traded.
    #: Pre-event observable (the HCP's own history), so no leakage.
    beta_recent_attendance_satiation: float = -1.75
    satiation_window_months: int = 3

    # --- calibration ------------------------------------------------------
    #: plan.md §11 / brief: overall verified-attendance rate among invitees to
    #: COMPLETED events must land in [26%, 32%]. The intercept t0 is solved by
    #: bisection against this target rather than hand-tuned.
    target_verified_attendance_rate: float = 0.29
    intercept_search_lo: float = -12.0
    intercept_search_hi: float = 12.0
    intercept_search_tol: float = 1e-7
    #: Acceptance band asserted by the generator after the real pass.
    accepted_rate_lo: float = 0.26
    accepted_rate_hi: float = 0.32

    # --- attendance record composition ------------------------------------
    #: Fraction of realised attenders whose attendance is *verifiable*. The
    #: remainder get AttendanceVerificationSource.UNVERIFIED and are refused as
    #: treatment by the default analysis specification (see enums.py).
    verified_fraction: float = 0.96
    #: Of the invitees who do not attend, the share that still leave a record:
    #: registered-then-no-show, and registered-then-cancelled. Everyone else has
    #: an invitation row and no attendance row at all.
    no_show_fraction_of_non_attendees: float = 0.18
    cancelled_registration_fraction_of_non_attendees: float = 0.07
    #: Session duration for verified attendees, minutes.
    duration_mean_minutes: float = 72.0
    duration_sd_minutes: float = 14.0
    duration_min_minutes: float = 20.0
    duration_max_minutes: float = 180.0

    # --- feature scales ---------------------------------------------------
    #: travel_friction[format] in [0, 1], before the region-remoteness
    #: multiplier. A virtual program costs the invitee nothing but an hour; an
    #: in-person dinner in a remote territory costs an evening and a drive.
    format_travel_friction: dict[str, float] = field(
        default_factory=lambda: {
            "IN_PERSON": 1.00,
            "ROUNDTABLE": 0.90,
            "HYBRID": 0.45,
            "VIRTUAL": 0.05,
            "ON_DEMAND": 0.00,
        }
    )
    #: How much region remoteness amplifies the format friction.
    travel_friction_remoteness_loading: float = 0.55
    #: topic_fit(specialty, topic): 1.0 when the topic sits in the specialty's
    #: own therapeutic area, the adjacent value when it is a neighbouring area,
    #: 0.0 otherwise. Drives both attendance and analytical eligibility.
    topic_fit_match: float = 1.0
    topic_fit_adjacent: float = 0.45
    topic_fit_mismatch: float = 0.0


# ===========================================================================
# True causal effect - plan.md §11 "heterogeneous, decaying event effects ...
# include zero-effect and negative/ineffective events"
# ===========================================================================


@dataclass(frozen=True, slots=True)
class EffectParams:
    """Hierarchical, heterogeneous, decaying per-attendee effect.

    ``effect_per_attendee`` is the *undecayed* monthly uplift in NRx for one
    verified attendee. The realised peak, in the first post month, is
    ``effect_per_attendee * exp(-1 / half_life_months)``.
    """

    #: m_global. With the component sds below, the 10th-90th percentile of a
    #: POSITIVE event lands near [0.30, 1.40] incremental NRx per attendee per
    #: month, which is the magnitude plan.md §11 asks for.
    m_global: float = 0.85
    #: Between-brand effect spread. Some brands genuinely have more to say.
    m_brand_sd: float = 0.18
    #: Between-topic spread. A new-indication topic moves more than a safety
    #: refresher.
    m_topic_sd: float = 0.14
    #: Between-region spread (local competitive intensity, access variation).
    m_region_sd: float = 0.10
    #: Residual per-event heterogeneity. plan.md §11 specifies Normal(0, 0.35).
    e_event_sd: float = 0.35
    #: Format offsets. Small-group roundtables move prescribing most per head;
    #: on-demand video least. These are the shape the Future Simulator has to
    #: learn, so they must be real and not noise.
    format_offsets: dict[str, float] = field(
        default_factory=lambda: {
            "ROUNDTABLE": 0.22,
            "IN_PERSON": 0.16,
            "HYBRID": 0.02,
            "VIRTUAL": -0.12,
            "ON_DEMAND": -0.20,
        }
    )
    #: Floor for a POSITIVE event, so the class label stays truthful.
    positive_floor: float = 0.05

    # --- effect composition (plan.md §11) ---------------------------------
    #: Exactly-zero-effect events. The estimator must return a CI covering zero
    #: for these, not a small positive number.
    zero_effect_share: float = 0.15
    #: Genuinely harmful/ineffective events - attendance displaced a rep call,
    #: the speaker was off-message, the competitor sponsored the dinner.
    negative_effect_share: float = 0.08
    negative_effect_mean: float = -0.25
    negative_effect_sd: float = 0.10

    # --- decay ------------------------------------------------------------
    #: half_life ~ Uniform(2.0, 5.0) months, applied for t in (t_event, t_event+6].
    half_life_lo: float = 2.0
    half_life_hi: float = 5.0
    #: Number of post months that carry any effect at all.
    decay_horizon_months: int = 6
    #: The 90-day primary window of plan.md §12.1: post months +1, +2, +3.
    #: The event month itself is deliberately neither pre nor post - a program
    #: on the 20th cannot plausibly move that month's scripts, and treating a
    #: partial month as "post" is a classic source of attenuation.
    post_window_months: int = 3


# ===========================================================================
# Market and marketing context
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ContextParams:
    """AR(1) market factors and HCP-month marketing activity.

    ``access_index`` and ``competitor_index`` are smooth walks per
    (brand, region) rather than white noise, because a formulary position does
    not resample itself every month - and because a *smooth* confounder is much
    harder for a naive before/after to survive.
    """

    # --- access_index ------------------------------------------------------
    access_mean: float = 0.62
    access_rho: float = 0.85
    access_innovation_sd: float = 0.045
    access_min: float = 0.20
    access_max: float = 0.95
    #: Between-(brand, region) spread of the long-run mean.
    access_cell_sd: float = 0.09

    # --- competitor_index --------------------------------------------------
    competitor_mean: float = 0.50
    competitor_rho: float = 0.88
    competitor_innovation_sd: float = 0.050
    competitor_min: float = 0.10
    competitor_max: float = 0.90
    competitor_cell_sd: float = 0.08
    #: Slow market-wide intensification of competition over the window.
    competitor_drift_per_year: float = 0.05

    # --- marketing activity (HCP x month) ---------------------------------
    #: log-mean of rep calls at an average-opportunity HCP. exp(0.35) ~ 1.4
    #: calls/month.
    rep_calls_log_intercept: float = 0.35
    #: Rep effort chases prescribing potential. This is what makes rep_calls a
    #: confounder rather than a nuisance covariate.
    rep_calls_opportunity_loading: float = 0.70
    #: Segment multiplier applied on the log scale, indexed by segment rank.
    rep_calls_segment_step: float = 0.22
    #: Field force takes the same summer/December dip everyone else does.
    rep_calls_seasonality_amp: float = 0.10
    emails_log_intercept: float = 1.30
    emails_opportunity_loading: float = 0.35
    samples_log_intercept: float = 0.55
    samples_opportunity_loading: float = 0.50
    #: Non-speaker-program exposures (webinars, congresses, ad boards). Kept
    #: independent of speaker attendance on purpose: it must remain a clean
    #: pre-event covariate, never a post-treatment one.
    other_exposures_log_intercept: float = -0.55
    other_exposures_opportunity_loading: float = 0.30

    # --- the promotional halo around a program ----------------------------
    # A speaker program is never a standalone intervention. The rep who builds
    # the invitation list is working that prescriber that quarter: calls go up
    # before the event to secure attendance and again afterwards to follow up on
    # it, and the brand's email and sample activity rides along. Since rep calls
    # already enter the outcome model (``g3_rep_calls``), this pushes prescribing
    # up around every *invited* program, whether or not the invitee turned up.
    #
    # It is the reason a naive attendee pre/post overstates program impact, which
    # is the story plan.md §24.5 has to be able to tell, and without it the DGP
    # has no such mechanism at all - measured, the naive ratio landed anywhere
    # between 0.0 and 4.7 depending only on the seed, because nothing systematic
    # was driving it.
    #
    # Critically the halo attaches to the *invitation*, not to attendance. It is
    # therefore a pre-treatment covariate, observable in ``marketing_activity``,
    # and shared by the invited non-attendees the controls are drawn from - so it
    # inflates the naive number and cancels in a matched comparison. Making it
    # attendee-differential instead would make the truth unrecoverable in
    # principle rather than merely hard, which is not a property worth simulating.
    #: Months before the event month that already carry the uplift. The invitation
    #: lands 10-45 days ahead, so one month is the honest window.
    halo_months_before: int = 1
    #: Months after the event month. Matches the 90-day outcome window: the
    #: follow-up conversation is exactly what the naive analyst mistakes for the
    #: program's own effect.
    halo_months_after: int = 3
    #: Extra expected rep calls as a fraction of that HCP's own baseline rate, at
    #: the peak of the window. An HCP on 1.4 calls/month goes to ~2.6.
    halo_rep_call_uplift: float = 0.85
    #: The same idea for emails and samples, weaker: those are campaign-driven
    #: and less tightly coupled to one program.
    halo_email_uplift: float = 0.35
    halo_sample_uplift: float = 0.30


# ===========================================================================
# Costs and finance
# ===========================================================================


@dataclass(frozen=True, slots=True)
class CostParams:
    """Fully loaded event cost model (plan.md §12.5 needs a real denominator)."""

    #: Per-category (fixed, per-planned-attendee) base amounts in tenant currency.
    #: Categories are TaxonomyKind.COST_CATEGORY values.
    category_fixed: dict[str, float] = field(
        default_factory=lambda: {
            "VENUE": 1800.0,
            "CATERING": 240.0,
            "SPEAKER_FEE": 2500.0,
            "AV_PRODUCTION": 900.0,
            "TRAVEL": 350.0,
            "MATERIALS": 180.0,
            "VENDOR_MANAGEMENT": 650.0,
            "COMPLIANCE_REVIEW": 450.0,
        }
    )
    category_per_attendee: dict[str, float] = field(
        default_factory=lambda: {
            "VENUE": 22.0,
            "CATERING": 65.0,
            "SPEAKER_FEE": 0.0,
            "AV_PRODUCTION": 6.0,
            "TRAVEL": 180.0,
            "MATERIALS": 12.0,
            "VENDOR_MANAGEMENT": 9.0,
            "COMPLIANCE_REVIEW": 0.0,
        }
    )
    #: Speaker fee multiplier by tier - a national KOL costs what a national KOL
    #: costs, and this is a material share of a small program's budget.
    speaker_tier_multiplier: dict[str, float] = field(
        default_factory=lambda: {
            "NATIONAL_KOL": 2.4,
            "REGIONAL_EXPERT": 1.4,
            "LOCAL_SPEAKER": 1.0,
        }
    )
    #: Categories that only apply to formats with physical presence.
    in_person_only: tuple[str, ...] = ("VENUE", "CATERING", "TRAVEL")
    #: Categories that only apply to formats with a broadcast component.
    virtual_only: tuple[str, ...] = ("AV_PRODUCTION",)
    #: Always present, so every event clears the ">= 1 fully loaded cost row"
    #: minimum in plan.md §11.
    always_present: tuple[str, ...] = ("SPEAKER_FEE", "VENDOR_MANAGEMENT")
    #: What a CANCELLED program still costs, as a share of the full line item.
    #: A venue deposit and the speaker's cancellation fee are not recoverable at
    #: two weeks' notice, and compliance review has already happened. An ROI
    #: engine that treats cancelled programs as free understates portfolio spend,
    #: so the data has to carry the committed remainder. Categories absent from
    #: this map cost nothing when the program does not happen.
    cancelled_committed_share: dict[str, float] = field(
        default_factory=lambda: {
            "VENUE": 0.35,
            "SPEAKER_FEE": 0.25,
            "VENDOR_MANAGEMENT": 0.60,
            "COMPLIANCE_REVIEW": 1.00,
            "MATERIALS": 0.40,
        }
    )
    #: Multiplicative lognormal noise on each line item.
    amount_noise_sigma: float = 0.18
    #: Travel scales with how far people have to come.
    travel_remoteness_loading: float = 1.6

    # --- finance assumptions ----------------------------------------------
    #: Net contribution per incremental NRx, drawn per brand. Finance owns this
    #: number in production; here it is synthetic and clearly labelled.
    contribution_per_nrx_lo: float = 85.0
    contribution_per_nrx_hi: float = 260.0
    #: plan.md §12.5 requires conservative/base/optimistic propagation.
    scenario_multiplier: dict[str, float] = field(
        default_factory=lambda: {
            "CONSERVATIVE": 0.72,
            "BASE": 1.00,
            "OPTIMISTIC": 1.28,
        }
    )
    #: Assumptions are effective-dated and get revised once mid-window, so the
    #: ROI engine has to pick the version in force at the event date.
    revision_uplift: float = 1.06


# ===========================================================================
# Imperfections - plan.md §11 "missing months, unmatched IDs, duplicate
# attendance, cancelled events, cost outliers and overlapping exposure"
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ImperfectionRates:
    """Deliberate mess. Each rate exists to make one ingestion or evidence gate
    fire on real data rather than on a hand-written fixture."""

    #: Source HCP identifiers present in vendor files with no crosswalk row.
    #: Ingestion must quarantine these as IdentityMatchStatus.UNMATCHED.
    unmatched_source_id_rate: float = 0.05
    #: Source identifiers that resolve to two masters. Never guessed - the
    #: steward decides (IdentityMatchStatus.AMBIGUOUS).
    ambiguous_source_id_rate: float = 0.01
    #: Same event + HCP submitted twice with a conflicting verification source.
    #: Reconciliation must be deterministic and auditable.
    duplicate_attendance_rate: float = 0.02
    #: Share of HCP-brand Rx series that have missing months. A *missing* month
    #: is an absent row; a genuine zero is a present row with nrx=0 and
    #: is_observed=true. Conflating them is the classic Rx-panel error.
    rx_gap_series_rate: float = 0.03
    rx_gap_min_months: int = 1
    rx_gap_max_months: int = 3
    #: Small-cell suppression: row present, suppression_flag=true, nrx null.
    rx_suppression_rate: float = 0.015
    #: Suppression is *selective*, and that is what makes it dangerous: only
    #: low-volume cells are withheld, so a pipeline that drops suppressed rows
    #: drops the bottom of the distribution and biases every mean upward. A cell
    #: is eligible for suppression only at or below this NRx count.
    suppression_max_nrx: float = 4.0
    #: Genuine structural zeros - HCP simply wrote nothing that month.
    genuine_zero_rate: float = 0.06
    #: Cost lines 4-8x the category median, to exercise outlier review.
    cost_outlier_event_rate: float = 0.02
    cost_outlier_multiplier_lo: float = 4.0
    cost_outlier_multiplier_hi: float = 8.0
    #: Share of events deliberately built to fail an evidence gate, so the
    #: product can demonstrate NOT_RELIABLY_ESTIMABLE rather than assert it.
    #: Half get too few attendees, half get shredded outcome coverage.
    sabotaged_event_rate: float = 0.04
    #: "Too few" per plan.md §12.3 minimum-sample gate.
    low_attendance_invitation_count: int = 14
    #: Fraction of a low-coverage event's attendees whose post-period Rx rows
    #: are removed, pushing outcome coverage below the 60% gate.
    low_coverage_attendee_drop_rate: float = 0.55
    #: Share of verified attendances that have another same-brand verified
    #: attendance within 90 days. The brief asks for ~0.06; that is arithmetically
    #: unreachable at the mandated invitation density without destroying the
    #: mandated confounding (config module docstring, deviation 4). This is the
    #: realised upper bound the generator asserts against - measured, reported in
    #: the manifest, never forced after the fact.
    max_overlapping_exposure_rate: float = 0.12


# ===========================================================================
# Vendor-shaped source files
# ===========================================================================


@dataclass(frozen=True, slots=True)
class SourceFileParams:
    """Shapes for the ``source/`` tree that flows through real ingestion.

    Files are deliberately *not* the canonical contract: real vendors send
    ``Event Code``, ``HCP ID``, ``dd/mm/yyyy`` and a UTF-8 BOM, and the mapping
    wizard of plan.md §10.3 exists precisely because of that.
    """

    #: One file per dataset type per quarter for time-series domains.
    partition_by_quarter: tuple[str, ...] = (
        "INVITATIONS",
        "ATTENDANCE",
        "RX_MONTHLY",
        "MARKETING_ACTIVITY",
        "EVENT_COST",
        "MARKET_FACTORS",
    )
    #: Date rendering per dataset type. Mixed on purpose (plan.md §10.3).
    date_formats: dict[str, str] = field(
        default_factory=lambda: {
            "CAMPAIGN_EVENT_MASTER": "%Y-%m-%d",
            "INVITATIONS": "%d/%m/%Y",
            "ATTENDANCE": "%d-%b-%Y",
            "RX_MONTHLY": "%Y-%m",
            "MARKETING_ACTIVITY": "%Y-%m",
            "MARKET_FACTORS": "%b-%Y",
            "EVENT_COST": "%m/%d/%Y",
            "FINANCE_ASSUMPTIONS": "%Y-%m-%d",
            "CANDIDATE_PROGRAMS": "%Y-%m",
        }
    )
    #: Dataset emitted as .xlsx to exercise the workbook reader (plan.md §10.3).
    xlsx_dataset: str = "ATTENDANCE"
    #: Dataset emitted with a UTF-8 BOM to exercise encoding detection.
    bom_dataset: str = "HCP_MASTER"
    #: Vendor that renders money with thousands separators, because one always does.
    thousands_separator_dataset: str = "EVENT_COST"


# ===========================================================================
# Volume minimums - PLAN_REVIEW F-2
# ===========================================================================


@dataclass(frozen=True, slots=True)
class VolumeTargets:
    """Hard minimums. ``generator.py`` raises ``SyntheticMinimumNotMet`` and the
    CLI exits non-zero if any of these is missed (plan.md §11)."""

    tenants: int
    brands_primary_tenant: int
    brands_secondary_tenant: int
    hcps_per_tenant: int
    campaigns: int
    events_total: int
    events_completed: int
    events_not_completed: int
    invitations: int
    verified_attendance: int
    rx_rows: int
    marketing_and_market_rows: int
    cost_rows_per_event: int
    months_of_history: int


# ===========================================================================
# Profiles
# ===========================================================================


@dataclass(frozen=True, slots=True)
class SyntheticProfile:
    """A complete, self-consistent generation recipe."""

    name: ProfileName

    # --- volumes ----------------------------------------------------------
    n_hcps_per_tenant: int
    n_brands_primary: int
    n_brands_secondary: int
    n_campaigns_primary: int
    n_campaigns_secondary: int
    n_events_completed: int
    n_events_cancelled: int
    n_events_proposed: int
    #: Share of events belonging to the primary tenant.
    primary_tenant_event_share: float
    months_of_history: int
    n_candidate_programs: int

    # --- panel density ----------------------------------------------------
    #: P(HCP is in a given brand's Rx panel), before the specialty-fit
    #: modulation and before the "every HCP prescribes at least one brand"
    #: guarantee. Higher in ``smoke``, where the shorter history has fewer months
    #: to accumulate rows and a denser panel keeps per-brand series long enough to
    #: fit a six-month pre-period against. It is not a lever on contamination -
    #: measured, halving it left the naive/true ratio unchanged.
    brand_panel_probability: float
    #: Mean invitations per event; NegBin, clipped to [min, max].
    invitations_per_event_mean: float
    invitations_per_event_min: int
    invitations_per_event_max: int
    #: Share of invitees flagged analytically ineligible (specialty out of the
    #: campaign's target list). They may still attend; the cohort builder drops
    #: them, which is what makes the funnel non-trivial.
    ineligible_invitation_rate: float

    # --- shared behaviour -------------------------------------------------
    targets: VolumeTargets
    outcome: OutcomeParams = field(default_factory=OutcomeParams)
    latent: LatentParams = field(default_factory=LatentParams)
    population: HcpPopulationParams = field(default_factory=HcpPopulationParams)
    design: EventDesignParams = field(default_factory=EventDesignParams)
    selection: SelectionParams = field(default_factory=SelectionParams)
    effect: EffectParams = field(default_factory=EffectParams)
    context: ContextParams = field(default_factory=ContextParams)
    cost: CostParams = field(default_factory=CostParams)
    imperfections: ImperfectionRates = field(default_factory=ImperfectionRates)
    source_files: SourceFileParams = field(default_factory=SourceFileParams)

    # --- derived ----------------------------------------------------------
    @property
    def n_events_total(self) -> int:
        return self.n_events_completed + self.n_events_cancelled + self.n_events_proposed

    @property
    def n_campaigns_total(self) -> int:
        return self.n_campaigns_primary + self.n_campaigns_secondary

    @property
    def panel_start_month(self) -> date:
        """First month of the Rx panel, counted back from the fixed anchor."""
        total = PANEL_END_MONTH.year * 12 + (PANEL_END_MONTH.month - 1)
        start = total - (self.months_of_history - 1)
        return date(start // 12, start % 12 + 1, 1)

    @property
    def completed_event_month_lo(self) -> int:
        """Earliest month index that can host a COMPLETED event.

        plan.md §12.1 asks for six pre-event months. Six is not enough, and this is
        the one place in the factory where the estimator's design dictates a
        generator constant.

        The causal engine cannot use the same six months as both the matching target
        and the difference-in-differences baseline. Doing so balances a noisy proxy
        for each prescriber's level rather than the level itself, which forces
        controls to be drawn from the top of their own month-to-month noise; they
        revert downward over the post window while the attendees do not, and the
        estimate reads the reversion as program impact. Measured, that inflated the
        estimate to roughly four times the known truth. The fix is a second,
        strictly earlier window - so a completed event needs
        ``pre_window_months + anchor_window_months`` = 12 clean months before it,
        and an event at month 6 has no more chance of being estimated honestly than
        one at month 0.
        """
        return 12

    @property
    def completed_event_month_hi(self) -> int:
        """Latest month index that can host a COMPLETED event.

        Three post-event months are required, and the event month itself is
        excluded from both windows, so the last usable index is T - 4.
        """
        return self.months_of_history - 4


def _smoke_targets() -> VolumeTargets:
    return VolumeTargets(
        tenants=2,
        brands_primary_tenant=3,
        brands_secondary_tenant=2,
        hcps_per_tenant=1_200,
        campaigns=8,
        events_total=260,
        events_completed=180,
        events_not_completed=80,
        invitations=9_600,
        verified_attendance=2_300,
        rx_rows=38_400,
        marketing_and_market_rows=12_000,
        cost_rows_per_event=1,
        months_of_history=18,
    )


def _full_targets() -> VolumeTargets:
    return VolumeTargets(
        tenants=2,
        brands_primary_tenant=5,
        brands_secondary_tenant=3,
        hcps_per_tenant=12_000,
        campaigns=96,
        events_total=5_400,
        events_completed=4_300,
        events_not_completed=1_100,
        invitations=216_000,
        verified_attendance=62_000,
        #: Well above plan.md's derived minimum of 499,000, and deliberately so:
        #: this is a tripwire on panel density, not a restatement of the brief. A
        #: change that quietly halves the Rx panel leaves every other assertion
        #: green while removing most of the data the estimator fits on, which is
        #: precisely the failure mode deviations 4-6 were. Realised: ~2.32M.
        rx_rows=2_200_000,
        marketing_and_market_rows=180_000,
        cost_rows_per_event=3,
        months_of_history=24,
    )


SMOKE = SyntheticProfile(
    name="smoke",
    n_hcps_per_tenant=1_200,
    n_brands_primary=3,
    n_brands_secondary=2,
    n_campaigns_primary=5,
    n_campaigns_secondary=3,
    n_events_completed=180,
    n_events_cancelled=45,
    n_events_proposed=35,
    primary_tenant_event_share=0.70,
    #: 30 rather than the 18 this profile carried first. The causal engine matches on
    #: a window strictly earlier than the baseline window (see
    #: ``EstimatorSpec.anchor_window_months``), so a completed event needs 12 clean
    #: pre-event months, not 6. At 18 months of panel the only months that could host
    #: an event were 12-14, which is too narrow a stagger for a cohort-time estimator
    #: to have anything to aggregate; measured at 18 months, a third of all units had
    #: no anchor window at all and were excluded for missing history. The volume
    #: targets are floors (``actual >= required``), so a longer panel satisfies them
    #: the same way.
    months_of_history=30,
    n_candidate_programs=40,
    brand_panel_probability=0.62,
    invitations_per_event_mean=50.0,
    invitations_per_event_min=18,
    invitations_per_event_max=120,
    ineligible_invitation_rate=0.08,
    targets=_smoke_targets(),
)

FULL = SyntheticProfile(
    name="full",
    n_hcps_per_tenant=12_000,
    n_brands_primary=5,
    n_brands_secondary=3,
    n_campaigns_primary=67,
    n_campaigns_secondary=29,
    n_events_completed=4_300,
    n_events_cancelled=660,
    n_events_proposed=440,
    primary_tenant_event_share=0.70,
    #: 36 rather than 24, for the reason given on the smoke profile: a completed
    #: event needs 12 clean pre-event months, and the event window has to stay wide
    #: enough to give the cohort-time estimator a real stagger to aggregate over.
    months_of_history=36,
    n_candidate_programs=240,
    brand_panel_probability=0.40,
    invitations_per_event_mean=55.0,
    invitations_per_event_min=18,
    invitations_per_event_max=120,
    ineligible_invitation_rate=0.08,
    targets=_full_targets(),
)

PROFILES: Final[dict[str, SyntheticProfile]] = {"smoke": SMOKE, "full": FULL}


def get_profile(name: str) -> SyntheticProfile:
    """Look up a profile by name, failing loudly on a typo."""
    try:
        return PROFILES[name]
    except KeyError:  # pragma: no cover - CLI validates first
        known = ", ".join(sorted(PROFILES))
        raise KeyError(f"unknown synthetic profile {name!r}; known profiles: {known}") from None
