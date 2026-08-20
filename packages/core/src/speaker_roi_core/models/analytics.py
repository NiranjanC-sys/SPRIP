"""Causal estimates, evidence grading, ROI, forecasts and the planning surface.

Everything in this schema is *derived*. It can always be recomputed from the
``core`` tables plus a run's parameters, which is why every table carries a
``run_id`` and why nothing here is edited in place - a correction is a new run.

Three design decisions in this schema are load-bearing and are easy to get wrong:

**Evidence is graded from gates, not from a score.** ``event_impacts.evidence_grade``
is a deterministic function of the boolean gate results in
``event_impact_gates``. There is no learned confidence, because a confidence
number invites "0.62 is probably fine" reasoning about a result that failed its
parallel-trends check. docs/PLAN_REVIEW.md F-4 makes this binding.

**An unmeasurable event is recorded as unmeasurable, never as zero.** A zero lift
and an unestimable lift are different claims; averaging the latter into a
portfolio as if it were the former understates good programs and overstates bad
ones. ``EvidenceStatus.NOT_RELIABLY_ESTIMABLE`` is a first-class outcome.

**Prescriber-grain model output never leaves this schema.** ``cohort_members``
and ``propensity_scores`` carry ``hcp_id`` alongside a score. Read together they
are a ranked targeting list, which plan.md §7.4 and §15 prohibit exposing.
docs/PLAN_REVIEW.md F-6 makes these analytics-tier only: no API response may
carry ``hcp_id`` next to a score or an outcome, and
``tests/security/test_no_hcp_grain_leak.py`` enforces it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from speaker_roi_core.db.base import (
    ActorMixin,
    Base,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
    tenant_code_unique,
    tenant_lookup_index,
    uuid_pk,
)
from speaker_roi_core.db.types import (
    JSONB,
    Currency,
    Fraction,
    Measure,
    Money,
    Quantity,
    Sha256,
    pg_enum,
)
from speaker_roi_core.enums import (
    AggregationLevel,
    AiAnswerMode,
    AiIntent,
    AiRefusalReason,
    AnalysisGrain,
    CohortArm,
    ConstraintKind,
    ControlStrategy,
    DatasetType,
    EstimatorKind,
    EvidenceGate,
    EvidenceGrade,
    EvidenceStatus,
    FailureCategory,
    FinanceScenario,
    ForecastMode,
    OptimizerStatus,
    OutcomeMetric,
    PublicationState,
    ReviewDecision,
    ReviewGate,
    RunKind,
    RunStatus,
    ScenarioStatus,
    SensitivityTest,
)

if TYPE_CHECKING:
    from speaker_roi_core.models.core import Brand, Event

# ===========================================================================
# Run lineage
# ===========================================================================


class AnalysisRun(Base, TenantMixin, TimestampMixin, ActorMixin):
    """One execution of an analytical job. The ``run_id`` in every lineage chip.

    plan.md §14 requires that a published number be reproducible. That is only
    true if the run records *everything* that could change the answer: the input
    data versions, the estimator specification, the finance version, the model
    version, the random seed and the code revision. All six live here.

    ``input_data_versions`` is a snapshot, not a live join, because the point of
    the record is what was true *then*.
    """

    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_analysis_runs_tenant_idempotency"
        ),
        tenant_lookup_index("analysis_runs", "run_kind", "status"),
        tenant_lookup_index("analysis_runs", "created_at"),
        tenant_lookup_index("analysis_runs", "status"),
        CheckConstraint(
            "status <> 'FAILED' OR failure_category IS NOT NULL",
            name="failed_run_states_category",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_kind: Mapped[RunKind] = mapped_column(pg_enum(RunKind), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        pg_enum(RunStatus), nullable=False, default=RunStatus.QUEUED
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    #: Filters and options the run was launched with, exactly as resolved.
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: ``{dataset_type: version_number}`` at launch time.
    input_data_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    estimator_spec_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    finance_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: Seed for every stochastic step (bootstrap, matching tie-breaks, LightGBM).
    #: Without it, two runs on identical data disagree in the third decimal and
    #: nobody can tell whether the data or the dice moved.
    random_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Git revision of the code that produced the result.
    code_version: Mapped[str | None] = mapped_column(String(60), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: Human-readable current step, surfaced on the job monitor.
    progress_note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    failure_category: Mapped[FailureCategory | None] = mapped_column(
        pg_enum(FailureCategory), nullable=True
    )
    failure_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    events_considered: Mapped[int | None] = mapped_column(Integer, nullable=True)
    events_measured: Mapped[int | None] = mapped_column(Integer, nullable=True)
    events_not_estimable: Mapped[int | None] = mapped_column(Integer, nullable=True)

    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Hash of (parameters + input versions + code version). Two runs with the
    #: same fingerprint must produce identical output; the reproducibility test
    #: asserts exactly that.
    fingerprint: Mapped[str | None] = mapped_column(Sha256, nullable=True)


class EstimatorSpec(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """A versioned causal-estimation *specification* - not a trained model.

    docs/PLAN_REVIEW.md F-1: the causal estimator is a statistical procedure, and
    forcing it through a model-registry lifecycle (train/validate/promote) was one
    of the confusions in the original plan. What genuinely needs versioning is the
    *specification*: which estimator, which control strategy, how many pre and
    post periods, the caliper, and the gate thresholds. Change any of those and
    the numbers move, so a published result names the spec it used.
    """

    __tablename__ = "estimator_specs"
    __table_args__ = (
        tenant_code_unique("estimator_specs", "code", "version"),
        tenant_lookup_index("estimator_specs", "is_active"),
        CheckConstraint("pre_periods >= 2", name="pre_periods_supports_trend_test"),
        CheckConstraint("post_periods >= 1", name="post_periods_positive"),
        CheckConstraint("caliper > 0", name="caliper_positive"),
        CheckConstraint("control_ratio >= 1", name="control_ratio_at_least_one"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)

    primary_estimator: Mapped[EstimatorKind] = mapped_column(
        pg_enum(EstimatorKind), nullable=False, default=EstimatorKind.COHORT_TIME_ATT
    )
    control_strategy: Mapped[ControlStrategy] = mapped_column(
        pg_enum(ControlStrategy), nullable=False, default=ControlStrategy.INVITED_NON_ATTENDEE
    )
    outcome_metric: Mapped[OutcomeMetric] = mapped_column(
        pg_enum(OutcomeMetric), nullable=False, default=OutcomeMetric.NRX
    )

    #: Months of history required before the event, and the measurement window
    #: after it. At least two pre-periods, or the parallel-trends test has
    #: nothing to test.
    pre_periods: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=6)
    post_periods: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    #: Months immediately around the event excluded from both windows, so
    #: same-month contamination does not leak treatment into the baseline.
    washout_periods: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    caliper: Mapped[float] = mapped_column(Measure, nullable=False, default=0.05)
    control_ratio: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    enforce_common_support: Mapped[bool] = mapped_column(nullable=False, default=True)
    matching_covariates: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    #: Gate thresholds: minimum treated, minimum controls, maximum absolute
    #: standardised mean difference, minimum outcome coverage, placebo p-value
    #: floor. Stored as data so a tenant can tighten them without a deploy - and
    #: so a published result can prove which thresholds it cleared.
    gate_thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: Bootstrap replicates for portfolio aggregation intervals.
    bootstrap_replicates: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    confidence_level: Mapped[float] = mapped_column(Fraction, nullable=False, default=0.95)

    is_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


# ===========================================================================
# Cohorts and prescriber-grain intermediates (never leave this schema)
# ===========================================================================


class Cohort(Base, TenantMixin, TimestampMixin):
    """The treated and control groups constructed for one event.

    Balance is stored, not just computed and discarded, because "we matched" is
    not evidence - "the largest standardised mean difference after matching was
    0.04 across 11 covariates" is. The Evidence drawer renders this directly.
    """

    __tablename__ = "cohorts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "event_id", name="uq_cohorts_run_event"),
        tenant_lookup_index("cohorts", "event_id"),
        CheckConstraint(
            "treated_count >= 0 AND control_count >= 0", name="arm_counts_non_negative"
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.events.id", ondelete="CASCADE"), nullable=False
    )

    control_strategy: Mapped[ControlStrategy] = mapped_column(
        pg_enum(ControlStrategy), nullable=False
    )
    #: Why this strategy was used. docs/PLAN_REVIEW.md F-9 forbids a silent
    #: fallback to a weaker control source: dropping from invited-non-attendee to
    #: a target-universe control caps the achievable grade and must be stated.
    strategy_justification: Mapped[str | None] = mapped_column(String(500), nullable=True)

    treated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    control_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_pairs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dropped_off_support: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dropped_no_match: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    caliper: Mapped[float | None] = mapped_column(Measure, nullable=True)
    control_ratio: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    #: Per-covariate SMD before and after matching, plus variance ratios.
    balance_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    max_abs_smd_after: Mapped[float | None] = mapped_column(Measure, nullable=True)
    propensity_model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    #: Overlap of the propensity distributions; a low value means the two arms
    #: are barely comparable regardless of what the matcher managed to pair.
    common_support_overlap: Mapped[float | None] = mapped_column(Fraction, nullable=True)

    event: Mapped[Event] = relationship()


class CohortMember(Base, TenantMixin):
    """One prescriber's assignment inside a cohort.

    ANALYTICS-TIER ONLY. This table pairs ``hcp_id`` with a propensity score and
    is therefore a ranked list of prescribers by predicted engagement - exactly
    the artefact plan.md §7.4 prohibits surfacing. No API response may include
    rows from this table at prescriber grain; the UI receives pre-aggregated
    balance and support diagnostics instead (docs/PLAN_REVIEW.md F-6).
    """

    __tablename__ = "cohort_members"
    __table_args__ = (
        UniqueConstraint("tenant_id", "cohort_id", "hcp_id", name="uq_cohort_members_cohort_hcp"),
        tenant_lookup_index("cohort_members", "cohort_id", "arm"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analytics.cohorts.id", ondelete="CASCADE"), nullable=False
    )
    hcp_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    arm: Mapped[CohortArm] = mapped_column(pg_enum(CohortArm), nullable=False)
    propensity_score: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    #: Matched set identifier; controls share the group of their treated unit.
    match_group: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Inverse-propensity or matching weight used in the outcome regression.
    weight: Mapped[float | None] = mapped_column(Measure, nullable=True)
    match_distance: Mapped[float | None] = mapped_column(Measure, nullable=True)


class PropensityScore(Base, TenantMixin):
    """M1 output: predicted attendance probability for an invited prescriber.

    ANALYTICS-TIER ONLY - see the warning on :class:`CohortMember`.

    docs/PLAN_REVIEW.md F-1 is explicit that this model exists *solely* to build
    comparable groups. It is not an attendance recommender and its scores are
    never used to choose whom to invite; that is the compliance line.
    """

    __tablename__ = "propensity_scores"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "run_id", "event_id", "hcp_id", name="uq_propensity_scores_grain"
        ),
        CheckConstraint("score >= 0 AND score <= 1", name="score_is_probability"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    hcp_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    score: Mapped[float] = mapped_column(Fraction, nullable=False)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


# ===========================================================================
# Impact
# ===========================================================================


class EventImpact(Base, TenantMixin, TimestampMixin, VersionMixin):
    """The estimated causal effect of one event on one outcome metric.

    ``att`` is the average treatment effect on the treated, in the units of
    ``outcome_metric`` per attendee per month. ``incremental_nrx`` scales it by
    the verified attendee count over the post window - the number the ROI
    calculation consumes.

    Nullable point estimates are intentional. When ``evidence_status`` is
    ``NOT_RELIABLY_ESTIMABLE`` the correct value is *absent*, not zero, and the
    schema enforces that a status of ``ESTIMATED`` is the only one permitted to
    carry a number.
    """

    __tablename__ = "event_impacts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "event_id",
            "outcome_metric",
            "grain",
            name="uq_event_impacts_grain",
        ),
        tenant_lookup_index("event_impacts", "event_id", "outcome_metric"),
        tenant_lookup_index("event_impacts", "evidence_grade", "publication_state"),
        tenant_lookup_index("event_impacts", "publication_state"),
        CheckConstraint(
            "evidence_status <> 'ESTIMATED' OR att IS NOT NULL",
            name="estimated_impact_has_value",
        ),
        CheckConstraint(
            "evidence_status = 'ESTIMATED' OR att IS NULL",
            name="unestimable_impact_has_no_value",
        ),
        CheckConstraint(
            "ci_low IS NULL OR ci_high IS NULL OR ci_high >= ci_low",
            name="interval_ordered",
        ),
        CheckConstraint(
            "evidence_status <> 'NOT_RELIABLY_ESTIMABLE' OR not_estimable_reason IS NOT NULL",
            name="unestimable_states_reason",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.events.id", ondelete="CASCADE"), nullable=False
    )
    cohort_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analytics.cohorts.id", ondelete="SET NULL"), nullable=True
    )
    outcome_metric: Mapped[OutcomeMetric] = mapped_column(pg_enum(OutcomeMetric), nullable=False)
    #: How finely the outcome could be linked. plan.md §3 requires dropping to a
    #: coarser grain *explicitly* when prescriber-level linkage is unavailable,
    #: rather than silently reporting a territory result as an HCP one.
    grain: Mapped[AnalysisGrain] = mapped_column(
        pg_enum(AnalysisGrain), nullable=False, default=AnalysisGrain.HCP
    )

    #: The estimator that produced ``att``. Cohort-time ATT is the primary
    #: specification; TWFE is retained as a diagnostic only, because with
    #: staggered adoption and heterogeneous effects it is biased by construction
    #: (docs/PLAN_REVIEW.md F-10).
    estimator_kind: Mapped[EstimatorKind] = mapped_column(pg_enum(EstimatorKind), nullable=False)

    att: Mapped[float | None] = mapped_column(Measure, nullable=True)
    standard_error: Mapped[float | None] = mapped_column(Measure, nullable=True)
    ci_low: Mapped[float | None] = mapped_column(Measure, nullable=True)
    ci_high: Mapped[float | None] = mapped_column(Measure, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Measure, nullable=True)
    confidence_level: Mapped[float] = mapped_column(Fraction, nullable=False, default=0.95)

    #: Total incremental volume attributable to the event over the post window.
    incremental_nrx: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    incremental_nrx_low: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    incremental_nrx_high: Mapped[float | None] = mapped_column(Quantity, nullable=True)

    n_treated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_control: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pre_periods: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    post_periods: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    #: Share of cohort members with observed outcomes across the window. Low
    #: coverage is a gate failure, not a footnote.
    outcome_coverage: Mapped[float | None] = mapped_column(Fraction, nullable=True)

    #: TWFE run alongside the primary estimator. A material divergence is itself
    #: a sensitivity signal and is surfaced, not hidden.
    twfe_att: Mapped[float | None] = mapped_column(Measure, nullable=True)
    twfe_divergence_flag: Mapped[bool] = mapped_column(nullable=False, default=False)

    evidence_status: Mapped[EvidenceStatus] = mapped_column(pg_enum(EvidenceStatus), nullable=False)
    evidence_grade: Mapped[EvidenceGrade] = mapped_column(pg_enum(EvidenceGrade), nullable=False)
    #: Enumerated cause when unestimable: INSUFFICIENT_ATTENDANCE,
    #: INSUFFICIENT_CONTROLS, INSUFFICIENT_COVERAGE, NO_PRE_PERIOD,
    #: PARALLEL_TRENDS_VIOLATED, OVERLAPPING_EXPOSURE.
    not_estimable_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)

    publication_state: Mapped[PublicationState] = mapped_column(
        pg_enum(PublicationState), nullable=False, default=PublicationState.DRAFT
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    #: Convenience denormalisation for portfolio filtering without a join to
    #: ``core.events`` on the hot path.
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    gates: Mapped[list[EventImpactGate]] = relationship(
        back_populates="event_impact", cascade="all, delete-orphan"
    )
    event_study_points: Mapped[list[EventStudyPoint]] = relationship(
        back_populates="event_impact", cascade="all, delete-orphan"
    )
    sensitivity_results: Mapped[list[SensitivityResult]] = relationship(
        back_populates="event_impact", cascade="all, delete-orphan"
    )


class EventImpactGate(Base, TenantMixin):
    """One evidence gate result. The grade is computed from these rows.

    Storing the observed value beside the threshold is what turns "MODERATE" from
    an opaque label into a defensible statement: the drawer can say "12 treated
    prescribers against a minimum of 20", and a reviewer can disagree with the
    threshold rather than with the arithmetic.
    """

    __tablename__ = "event_impact_gates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "event_impact_id", "gate", name="uq_event_impact_gates_impact_gate"
        ),
        tenant_lookup_index("event_impact_gates", "gate", "passed"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_impact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.event_impacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    gate: Mapped[EvidenceGate] = mapped_column(pg_enum(EvidenceGate), nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    observed_value: Mapped[float | None] = mapped_column(Measure, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Measure, nullable=True)
    #: ``True`` when failing this gate makes the estimate unusable rather than
    #: merely weaker.
    is_critical: Mapped[bool] = mapped_column(nullable=False, default=False)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)

    event_impact: Mapped[EventImpact] = relationship(back_populates="gates")


class EventStudyPoint(Base, TenantMixin):
    """One lead/lag coefficient from the event-study specification.

    plan.md §12.3 requires the event-study chart because it is the honest way to
    show parallel trends: pre-period coefficients indistinguishable from zero are
    the visual argument that the design holds. Negative ``relative_period`` values
    are leads (before the event).
    """

    __tablename__ = "event_study_points"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "event_impact_id",
            "relative_period",
            name="uq_event_study_points_impact_period",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_impact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.event_impacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    relative_period: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    coefficient: Mapped[float | None] = mapped_column(Measure, nullable=True)
    standard_error: Mapped[float | None] = mapped_column(Measure, nullable=True)
    ci_low: Mapped[float | None] = mapped_column(Measure, nullable=True)
    ci_high: Mapped[float | None] = mapped_column(Measure, nullable=True)
    n_observations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The omitted reference period, conventionally -1.
    is_reference: Mapped[bool] = mapped_column(nullable=False, default=False)

    event_impact: Mapped[EventImpact] = relationship(back_populates="event_study_points")


class SensitivityResult(Base, TenantMixin):
    """One robustness check.

    plan.md §12.6 requires placebo and sensitivity analyses to run as part of
    every estimate rather than on request. A placebo test that "finds" an effect
    in a pre-period is evidence the design is broken, and that must reach the
    reviewer automatically - a check nobody runs is a check that always passes.
    """

    __tablename__ = "sensitivity_results"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "event_impact_id", "test", name="uq_sensitivity_results_impact_test"
        ),
        tenant_lookup_index("sensitivity_results", "test", "passed"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_impact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.event_impacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    test: Mapped[SensitivityTest] = mapped_column(pg_enum(SensitivityTest), nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    statistic: Mapped[float | None] = mapped_column(Measure, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Measure, nullable=True)
    #: Effect estimate under this alternative specification, so the drawer can
    #: show how far the headline moves when an assumption is relaxed.
    alternative_estimate: Mapped[float | None] = mapped_column(Measure, nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    event_impact: Mapped[EventImpact] = relationship(back_populates="sensitivity_results")


# ===========================================================================
# Money
# ===========================================================================


class RoiResult(Base, TenantMixin, TimestampMixin, VersionMixin):
    """Monetised impact at event, campaign, brand or portfolio grain.

    Every row names its ``finance_version_id``. plan.md §14 requires it, and the
    reason is practical: contribution margin gets revised, and without the version
    a change in reported ROI is indistinguishable from a change in performance.

    Intervals propagate from the impact estimate. A point ROI without an interval
    invites false precision on a number built from an estimate with real
    uncertainty.
    """

    __tablename__ = "roi_results"
    __table_args__ = (
        tenant_lookup_index("roi_results", "run_id"),
        tenant_lookup_index("roi_results", "event_id"),
        tenant_lookup_index("roi_results", "brand_id", "level"),
        tenant_lookup_index("roi_results", "publication_state"),
        CheckConstraint("total_cost >= 0", name="total_cost_non_negative"),
        CheckConstraint("level <> 'EVENT' OR event_id IS NOT NULL", name="event_level_names_event"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    level: Mapped[AggregationLevel] = mapped_column(pg_enum(AggregationLevel), nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.events.id", ondelete="CASCADE"), nullable=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    event_impact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.event_impacts.id", ondelete="SET NULL"),
        nullable=True,
    )

    finance_version_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scenario: Mapped[FinanceScenario] = mapped_column(
        pg_enum(FinanceScenario), nullable=False, default=FinanceScenario.BASE
    )
    contribution_per_nrx: Mapped[float | None] = mapped_column(Money, nullable=True)

    incremental_nrx: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    incremental_nrx_low: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    incremental_nrx_high: Mapped[float | None] = mapped_column(Quantity, nullable=True)

    gross_contribution: Mapped[float | None] = mapped_column(Money, nullable=True)
    total_cost: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    net_roi: Mapped[float | None] = mapped_column(Money, nullable=True)
    #: Benefit-cost ratio. Null rather than zero when impact is unestimable.
    benefit_cost_ratio: Mapped[float | None] = mapped_column(Measure, nullable=True)
    benefit_cost_ratio_low: Mapped[float | None] = mapped_column(Measure, nullable=True)
    benefit_cost_ratio_high: Mapped[float | None] = mapped_column(Measure, nullable=True)
    cost_per_incremental_nrx: Mapped[float | None] = mapped_column(Money, nullable=True)
    cost_per_attendee: Mapped[float | None] = mapped_column(Money, nullable=True)

    currency: Mapped[str] = mapped_column(Currency, nullable=False)
    #: Tenant reporting currency figures, converted at dated rates.
    reporting_currency: Mapped[str | None] = mapped_column(Currency, nullable=True)
    net_roi_reporting: Mapped[float | None] = mapped_column(Money, nullable=True)

    evidence_status: Mapped[EvidenceStatus] = mapped_column(pg_enum(EvidenceStatus), nullable=False)
    evidence_grade: Mapped[EvidenceGrade] = mapped_column(pg_enum(EvidenceGrade), nullable=False)
    #: For aggregates: how many contributing events sat at each grade, so a
    #: portfolio number cannot hide that most of it rests on weak evidence.
    evidence_mix: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    events_measured: Mapped[int | None] = mapped_column(Integer, nullable=True)
    events_excluded: Mapped[int | None] = mapped_column(Integer, nullable=True)

    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    publication_state: Mapped[PublicationState] = mapped_column(
        pg_enum(PublicationState), nullable=False, default=PublicationState.DRAFT
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Review(Base, TenantMixin, TimestampMixin):
    """A human decision on whether a result may be published.

    Append-only. plan.md §6.2 puts a compliance gate between an estimate and a
    published number; the record of who approved what, on which evidence, is the
    artefact an audit asks for. Storing the grade and gate summary at decision
    time means a later re-run cannot retroactively change what the reviewer saw.
    """

    __tablename__ = "reviews"
    __rls__: ClassVar[str | None] = "append_only"
    __table_args__ = (
        tenant_lookup_index("reviews", "event_impact_id", "created_at"),
        tenant_lookup_index("reviews", "decision"),
        tenant_lookup_index("reviews", "gate"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_impact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.event_impacts.id", ondelete="CASCADE"),
        nullable=True,
    )
    roi_result_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    gate: Mapped[ReviewGate] = mapped_column(pg_enum(ReviewGate), nullable=False)
    decision: Mapped[ReviewDecision] = mapped_column(pg_enum(ReviewDecision), nullable=False)
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    #: Mandatory for rejection and for approving anything below STRONG - an
    #: unexplained override is the thing this gate exists to prevent.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_state: Mapped[PublicationState | None] = mapped_column(
        pg_enum(PublicationState), nullable=True
    )
    new_state: Mapped[PublicationState | None] = mapped_column(
        pg_enum(PublicationState), nullable=True
    )
    #: Snapshot of the evidence at decision time.
    evidence_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


# ===========================================================================
# Forward-looking (M3/M4) and planning
# ===========================================================================


class Forecast(Base, TenantMixin, TimestampMixin):
    """M3 output: predicted impact of a program that has not happened yet.

    This is the model the brief actually needed and the original plan conflated
    with three other things (docs/PLAN_REVIEW.md F-1). Two properties make it
    honest rather than decorative:

    ``mode`` distinguishes a real model prediction from a pooled-prior fallback
    and from a refusal. When a proposed program falls outside the support of the
    training data - an unseen topic, a region with five historical events, an
    attendance figure beyond anything observed - the model returns
    ``OUT_OF_SUPPORT`` and no number at all. Extrapolating there is how a planning
    tool loses its credibility in one bad quarter.

    ``pi_low``/``pi_high`` are split-conformal prediction intervals calibrated on
    a temporal holdout, so they carry a coverage guarantee rather than a modelled
    variance that assumes the model is correct.
    """

    __tablename__ = "forecasts"
    __table_args__ = (
        tenant_lookup_index("forecasts", "run_id"),
        tenant_lookup_index("forecasts", "candidate_program_id"),
        tenant_lookup_index("forecasts", "mode"),
        CheckConstraint(
            "mode <> 'OUT_OF_SUPPORT' OR point_estimate IS NULL",
            name="refusal_carries_no_estimate",
        ),
        CheckConstraint(
            "mode = 'OUT_OF_SUPPORT' OR point_estimate IS NOT NULL",
            name="prediction_carries_estimate",
        ),
        CheckConstraint(
            "mode <> 'OUT_OF_SUPPORT' OR out_of_support_reasons IS NOT NULL",
            name="refusal_names_reasons",
        ),
        CheckConstraint(
            "pi_low IS NULL OR pi_high IS NULL OR pi_high >= pi_low", name="interval_ordered"
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    candidate_program_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.candidate_programs.id", ondelete="CASCADE"),
        nullable=True,
    )
    #: Set when forecasting a hypothetical from the simulator rather than a
    #: persisted candidate.
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    mode: Mapped[ForecastMode] = mapped_column(pg_enum(ForecastMode), nullable=False)

    #: Expected incremental prescriptions per attendee over the post window.
    point_estimate: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    pi_low: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    pi_high: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    alpha: Mapped[float] = mapped_column(Fraction, nullable=False, default=0.20)

    #: Effective sample size of the pooling cell that produced the prior. This is
    #: what drives the blend weight between model and prior, and it is shown to
    #: the user because "based on 4 similar events" is essential context.
    n_effective: Mapped[float | None] = mapped_column(Measure, nullable=True)
    pooling_cell: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pooling_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    blend_weight: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    #: Which features fell outside the training support, named individually so
    #: the planner can adjust the program rather than guess.
    out_of_support_reasons: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )

    #: M4 output, kept alongside because expected reach scales the impact.
    expected_attendance: Mapped[float | None] = mapped_column(Measure, nullable=True)
    expected_attendance_low: Mapped[float | None] = mapped_column(Measure, nullable=True)
    expected_attendance_high: Mapped[float | None] = mapped_column(Measure, nullable=True)

    expected_incremental_nrx: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    expected_cost: Mapped[float | None] = mapped_column(Money, nullable=True)
    expected_net_roi: Mapped[float | None] = mapped_column(Money, nullable=True)
    #: Lower-bound ROI, used by the optimizer's risk-aware objective so a wide
    #: interval is penalised rather than ignored.
    expected_net_roi_low: Mapped[float | None] = mapped_column(Money, nullable=True)
    currency: Mapped[str | None] = mapped_column(Currency, nullable=True)

    #: Per-feature contributions for the explanation panel. Never prescriber-level.
    drivers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)


class Scenario(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """A saved planning exercise: a budget, a horizon and a constraint set."""

    __tablename__ = "scenarios"
    __table_args__ = (
        tenant_code_unique("scenarios", "code"),
        tenant_lookup_index("scenarios", "status", "brand_id"),
        CheckConstraint("budget_total >= 0", name="budget_non_negative"),
        CheckConstraint("horizon_end >= horizon_start", name="horizon_ordered"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[ScenarioStatus] = mapped_column(
        pg_enum(ScenarioStatus), nullable=False, default=ScenarioStatus.DRAFT
    )
    horizon_start: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_end: Mapped[date] = mapped_column(Date, nullable=False)
    budget_total: Mapped[float] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(Currency, nullable=False)
    #: Share of budget reserved for programs the model refuses to score, so
    #: OUT_OF_SUPPORT designs can still be trialled deliberately instead of being
    #: frozen out permanently by their own novelty.
    exploration_budget_share: Mapped[float] = mapped_column(Fraction, nullable=False, default=0.10)
    finance_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    constraints: Mapped[list[ScenarioConstraint]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )


class ScenarioConstraint(Base, TenantMixin, TimestampMixin, ActorMixin):
    """One planning constraint: a floor, a cap or a required minimum.

    Held as data rather than code because the optimizer must be able to report
    *which* constraint made a problem infeasible, by name, in the UI (plan.md
    §7.5). Silently relaxing a constraint to force a solution is prohibited.
    """

    __tablename__ = "scenario_constraints"
    __table_args__ = (
        tenant_lookup_index("scenario_constraints", "scenario_id", "kind"),
        CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR max_value >= min_value",
            name="constraint_bounds_ordered",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[ConstraintKind] = mapped_column(pg_enum(ConstraintKind), nullable=False)
    #: The dimension value the constraint applies to (a region code, a brand
    #: code, a quarter). Null means it applies globally.
    key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    min_value: Mapped[float | None] = mapped_column(Measure, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Measure, nullable=True)
    is_hard: Mapped[bool] = mapped_column(nullable=False, default=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    scenario: Mapped[Scenario] = relationship(back_populates="constraints")


class OptimizerRun(Base, TenantMixin, TimestampMixin):
    """One solve of the budget allocation problem.

    ``infeasibility`` is populated when no allocation satisfies the constraints.
    plan.md §7.5 requires naming the conflicting constraints rather than returning
    an empty plan - "no solution" without a reason is indistinguishable from a
    bug, and a planner cannot act on it.
    """

    __tablename__ = "optimizer_runs"
    __table_args__ = (
        tenant_lookup_index("optimizer_runs", "scenario_id", "created_at"),
        tenant_lookup_index("optimizer_runs", "status"),
        CheckConstraint(
            "status <> 'INFEASIBLE' OR infeasibility IS NOT NULL",
            name="infeasible_run_explains_itself",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.analysis_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[OptimizerStatus] = mapped_column(pg_enum(OptimizerStatus), nullable=False)
    solver: Mapped[str] = mapped_column(String(40), nullable=False, default="HiGHS")
    objective_value: Mapped[float | None] = mapped_column(Money, nullable=True)
    #: Objective computed on the lower interval bound, reported beside the point
    #: objective so a plan that looks good only on optimistic assumptions is
    #: visible as such.
    objective_value_conservative: Mapped[float | None] = mapped_column(Money, nullable=True)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost: Mapped[float | None] = mapped_column(Money, nullable=True)
    budget_utilisation: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    solve_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mip_gap: Mapped[float | None] = mapped_column(Measure, nullable=True)
    #: Which constraints are tight at the optimum - the actionable answer to
    #: "what is holding this plan back".
    binding_constraints: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    #: Irreducible conflicting constraint set when infeasible.
    infeasibility: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class ScenarioAllocation(Base, TenantMixin, TimestampMixin):
    """One candidate's place in a solved plan."""

    __tablename__ = "scenario_allocations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "optimizer_run_id",
            "candidate_program_id",
            name="uq_scenario_allocations_run_candidate",
        ),
        tenant_lookup_index("scenario_allocations", "optimizer_run_id", "is_selected"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    optimizer_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.optimizer_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_program_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.candidate_programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    forecast_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.forecasts.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_selected: Mapped[bool] = mapped_column(nullable=False, default=False)
    allocated_cost: Mapped[float | None] = mapped_column(Money, nullable=True)
    expected_incremental_nrx: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    expected_net_roi: Mapped[float | None] = mapped_column(Money, nullable=True)
    #: Funded from the exploration reserve rather than the main objective.
    funded_from_exploration: Mapped[bool] = mapped_column(nullable=False, default=False)
    #: Why a candidate was not selected: dominated, constraint-excluded,
    #: compliance-ineligible, or out of support with exploration exhausted.
    exclusion_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ===========================================================================
# Governed assistant and data health
# ===========================================================================


class AiInteraction(Base, TenantMixin):
    """Append-only log of every assistant question and answer.

    plan.md §7.7 constrains the assistant to allowlisted intents answered from
    pre-computed facts; the model narrates, it never computes and never writes
    SQL. This table is the evidence that the constraint held: ``intent`` shows the
    request was classified into the allowlist, ``fact_payload_hash`` pins the exact
    numbers handed to the model, and ``refusal_reason`` records the cases it
    declined - including ``HCP_TARGETING``, which must always refuse.

    ``question_redacted`` is stored rather than the raw text because a free-text
    box is where sensitive content arrives whether or not it is invited.
    """

    __tablename__ = "ai_interactions"
    __rls__: ClassVar[str | None] = "append_only"
    __table_args__ = (
        tenant_lookup_index("ai_interactions", "created_at"),
        tenant_lookup_index("ai_interactions", "intent", "answer_mode"),
        tenant_lookup_index("ai_interactions", "refusal_reason"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    intent: Mapped[AiIntent | None] = mapped_column(pg_enum(AiIntent), nullable=True)
    answer_mode: Mapped[AiAnswerMode] = mapped_column(pg_enum(AiAnswerMode), nullable=False)
    refusal_reason: Mapped[AiRefusalReason | None] = mapped_column(
        pg_enum(AiRefusalReason), nullable=True
    )

    question_redacted: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    #: The filters the intent resolved to, after the caller's scope was applied.
    resolved_filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Hash of the structured facts passed to the model. Lets a disputed answer be
    #: checked against exactly the numbers that produced it.
    fact_payload_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    #: The analysis runs whose published results backed the answer.
    source_run_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: True when the deterministic template answered because the model was
    #: unavailable - the assistant degrades, it does not fail.
    used_offline_fallback: Mapped[bool] = mapped_column(nullable=False, default=False)
    user_feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DataHealthSnapshot(Base, TenantMixin, TimestampMixin):
    """Per-dataset readiness at a point in time.

    plan.md §7.6 requires the platform to say whether the data is good enough to
    measure *before* someone acts on a number. Coverage, freshness, unmatched rate
    and missing-month rate are the four that actually block estimation; the rest
    is context.
    """

    __tablename__ = "data_health_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "dataset_type", "computed_at", name="uq_data_health_snapshots_grain"
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    dataset_type: Mapped[DatasetType] = mapped_column(pg_enum(DatasetType), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    coverage_pct: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    freshness_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_period: Mapped[date | None] = mapped_column(Date, nullable=True)
    unmatched_pct: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    ambiguous_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_month_pct: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    quarantine_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplicate_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 0-100 composite, shown with its components rather than alone - a single
    #: number is only useful if you can see what dragged it down.
    readiness_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    #: Named problems that currently prevent measurement.
    blocking_issues: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    #: Set when the supplier changed a metric definition mid-series, which
    #: invalidates comparisons across the boundary.
    definition_change_flag: Mapped[bool] = mapped_column(nullable=False, default=False)


class PortfolioAggregate(Base, TenantMixin, TimestampMixin):
    """Pre-computed roll-up for the portfolio view.

    Materialised because the portfolio page must open in under two seconds over
    thousands of events (plan.md §16), and because aggregating estimates correctly
    is not a SUM: intervals combine through a block bootstrap that respects the
    clustering, which is not expressible in the page's query.
    """

    __tablename__ = "portfolio_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "level",
            "level_key",
            "period_start",
            name="uq_portfolio_aggregates_grain",
        ),
        tenant_lookup_index("portfolio_aggregates", "brand_id", "period_start"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics.analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    level: Mapped[AggregationLevel] = mapped_column(pg_enum(AggregationLevel), nullable=False)
    #: The dimension value being aggregated - a brand code, topic code, region
    #: code or format. ``ALL`` for the portfolio total.
    level_key: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Set when ``level`` is brand-grained, null for the portfolio total and for roll-ups by
    #: topic, region or format. A real foreign key, matching every other brand reference in the
    #: schema: an aggregate whose ``brand_id`` resolves to nothing renders on the portfolio page
    #: as a row with a blank brand name and no error, and ``RESTRICT`` is what makes that
    #: unreachable rather than merely unlikely.
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.brands.id", ondelete="RESTRICT"),
        nullable=True,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    events_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    events_measured: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    events_not_estimable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attendees_verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    incremental_nrx: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    incremental_nrx_low: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    incremental_nrx_high: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Money, nullable=True)
    net_roi: Mapped[float | None] = mapped_column(Money, nullable=True)
    benefit_cost_ratio: Mapped[float | None] = mapped_column(Measure, nullable=True)
    currency: Mapped[str | None] = mapped_column(Currency, nullable=True)

    #: Count of contributing events by grade. A portfolio number whose mix is
    #: mostly DIRECTIONAL is presented differently from one that is mostly STRONG.
    evidence_mix: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    dominant_grade: Mapped[EvidenceGrade | None] = mapped_column(
        pg_enum(EvidenceGrade), nullable=True
    )
    publication_state: Mapped[PublicationState] = mapped_column(
        pg_enum(PublicationState), nullable=False, default=PublicationState.DRAFT
    )

    brand: Mapped[Brand | None] = relationship()


__all__ = [  # noqa: RUF022 - grouped by concern, not alphabetised
    # lineage
    "AnalysisRun",
    "EstimatorSpec",
    # cohorts (analytics-tier only)
    "Cohort",
    "CohortMember",
    "PropensityScore",
    # impact
    "EventImpact",
    "EventImpactGate",
    "EventStudyPoint",
    "SensitivityResult",
    # money
    "RoiResult",
    "Review",
    # forward-looking
    "Forecast",
    "Scenario",
    "ScenarioConstraint",
    "OptimizerRun",
    "ScenarioAllocation",
    # assistant and health
    "AiInteraction",
    "DataHealthSnapshot",
    "PortfolioAggregate",
]
