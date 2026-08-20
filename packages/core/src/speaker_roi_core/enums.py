"""The platform's controlled vocabularies.

Every one of these becomes a native PostgreSQL enum (plan.md §8.1.1: "PostgreSQL
enums or checked reference tables for states, and JSONB only for variable
metadata"). They are declared once here and imported by the models, the API
schemas, the analytics library and the generated TypeScript contracts, so a state
cannot drift between layers.

Values are UPPER_SNAKE strings rather than integers: they show up verbatim in
audit rows, error reports and CSV exports, where a reader needs to understand
them without a lookup table.
"""

from __future__ import annotations

from enum import StrEnum


class StrEnumBase(StrEnum):
    """Base with the two helpers the API and migrations need."""

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]

    @classmethod
    def pg_name(cls) -> str:
        """Name of the backing PostgreSQL type (``snake_case`` of the class)."""
        out: list[str] = []
        for i, ch in enumerate(cls.__name__):
            if ch.isupper() and i:
                out.append("_")
            out.append(ch.lower())
        return "".join(out)


# ===========================================================================
# Tenancy, identity and access
# ===========================================================================


class TenantStatus(StrEnumBase):
    """Lifecycle of a pharmaceutical-company tenant (plan.md §5.4)."""

    PENDING_ONBOARDING = "PENDING_ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    #: Read-only wind-down. Data is retained, no new writes accepted.
    ARCHIVED = "ARCHIVED"


class Role(StrEnumBase):
    """The nine roles of plan.md §5.2.

    A user may hold several roles inside one tenant; effective permission is the
    union. ``PLATFORM_ADMIN`` is the only role that exists outside a tenant, and
    it deliberately grants no access to tenant business data (plan.md §5.4).
    """

    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    PHARMA_ADMIN = "PHARMA_ADMIN"
    VENDOR_CONTRIBUTOR = "VENDOR_CONTRIBUTOR"
    DATA_STEWARD = "DATA_STEWARD"
    ANALYTICS_LEAD = "ANALYTICS_LEAD"
    FINANCE_REVIEWER = "FINANCE_REVIEWER"
    COMPLIANCE_REVIEWER = "COMPLIANCE_REVIEWER"
    BRAND_MANAGER = "BRAND_MANAGER"
    EXECUTIVE_VIEWER = "EXECUTIVE_VIEWER"

    @property
    def is_platform(self) -> bool:
        return self is Role.PLATFORM_ADMIN

    @property
    def landing_route(self) -> str:
        """Post-login destination from the plan.md §5.3 table."""
        return _LANDING_ROUTES[self]


_LANDING_ROUTES: dict[Role, str] = {
    Role.PLATFORM_ADMIN: "/platform/companies",
    Role.PHARMA_ADMIN: "/admin/company",
    Role.VENDOR_CONTRIBUTOR: "/vendor/uploads",
    Role.DATA_STEWARD: "/data-health",
    Role.ANALYTICS_LEAD: "/portfolio",
    Role.FINANCE_REVIEWER: "/finance",
    Role.COMPLIANCE_REVIEWER: "/reviews",
    Role.BRAND_MANAGER: "/portfolio",
    Role.EXECUTIVE_VIEWER: "/portfolio",
}

#: Precedence used to pick a landing route when a user holds several roles.
#: Most operationally specific first, so a Vendor Contributor who is also an
#: Executive Viewer lands on their upload queue rather than a dashboard they
#: mostly cannot populate.
ROLE_LANDING_PRECEDENCE: tuple[Role, ...] = (
    Role.PLATFORM_ADMIN,
    Role.VENDOR_CONTRIBUTOR,
    Role.PHARMA_ADMIN,
    Role.DATA_STEWARD,
    Role.FINANCE_REVIEWER,
    Role.COMPLIANCE_REVIEWER,
    Role.ANALYTICS_LEAD,
    Role.BRAND_MANAGER,
    Role.EXECUTIVE_VIEWER,
)


class MembershipStatus(StrEnumBase):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    #: Effective-dated end reached; kept for audit lineage (plan.md §5.4).
    EXPIRED = "EXPIRED"


class UserStatus(StrEnumBase):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    LOCKED = "LOCKED"


class InvitationStatus(StrEnumBase):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AuthProviderKind(StrEnumBase):
    """See docs/PLAN_REVIEW.md F-3 - both are real implementations."""

    LOCAL = "LOCAL"
    OIDC = "OIDC"


class VendorStatus(StrEnumBase):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class DatasetAccess(StrEnumBase):
    """Direction of a vendor's dataset grant (docs/PLAN_REVIEW.md F-8).

    A licensed Rx supplier must be able to *submit* prescription outcomes while
    plan.md §5.5 forbids ever *showing* prescription outcomes to a vendor. The
    grant is therefore directional; ``WRITE`` is the Rx supplier's grant.
    """

    WRITE = "WRITE"
    READ = "READ"
    READ_WRITE = "READ_WRITE"


# ===========================================================================
# Commercial hierarchy
# ===========================================================================


class EventStatus(StrEnumBase):
    """plan.md §6: cancelled events never create treatment exposure."""

    PROPOSED = "PROPOSED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    @property
    def creates_exposure(self) -> bool:
        return self is EventStatus.COMPLETED


class EventFormat(StrEnumBase):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"
    HYBRID = "HYBRID"
    #: Small-group peer discussion, typically 6-12 attendees.
    ROUNDTABLE = "ROUNDTABLE"
    #: Recorded/on-demand session with verified view completion.
    ON_DEMAND = "ON_DEMAND"


class CampaignStatus(StrEnumBase):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaxonomyKind(StrEnumBase):
    """Tenant-scoped controlled lists.

    Region, topic and specialty are tenant-specific business vocabularies rather
    than universal enums - one customer's "EMEA West" is another's "Iberia". They
    live in ``core.taxonomy_values`` so upload validation can reject an unknown
    value with a precise message instead of silently accepting free text.
    """

    REGION = "REGION"
    TOPIC = "TOPIC"
    SPECIALTY = "SPECIALTY"
    PRACTICE_TYPE = "PRACTICE_TYPE"
    HCP_SEGMENT = "HCP_SEGMENT"
    COST_CATEGORY = "COST_CATEGORY"
    MARKETING_CHANNEL = "MARKETING_CHANNEL"
    THERAPEUTIC_AREA = "THERAPEUTIC_AREA"


class InvitationChannel(StrEnumBase):
    EMAIL = "EMAIL"
    REP = "REP"
    PORTAL = "PORTAL"
    PHONE = "PHONE"
    OTHER = "OTHER"


class AttendanceStatus(StrEnumBase):
    """Registration state. Distinct from ``verified_attended``.

    plan.md §12.1: treatment requires *verified* attendance, so a REGISTERED row
    with ``verified_attended = false`` is a control candidate, not a treatment.
    """

    NOT_REGISTERED = "NOT_REGISTERED"
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    ATTENDED = "ATTENDED"


class AttendanceVerificationSource(StrEnumBase):
    """How attendance was proven. Drives the evidence funnel."""

    BADGE_SCAN = "BADGE_SCAN"
    SIGN_IN_SHEET = "SIGN_IN_SHEET"
    WEBINAR_PLATFORM_LOG = "WEBINAR_PLATFORM_LOG"
    VENDOR_ATTESTATION = "VENDOR_ATTESTATION"
    #: Present in the file but with no supporting evidence column - accepted as a
    #: record, refused as treatment by the default analysis specification.
    UNVERIFIED = "UNVERIFIED"

    @property
    def is_strong(self) -> bool:
        return self in {
            AttendanceVerificationSource.BADGE_SCAN,
            AttendanceVerificationSource.WEBINAR_PLATFORM_LOG,
        }


class IdentityMatchStatus(StrEnumBase):
    """Crosswalk resolution state (plan.md §10.2 step 8)."""

    MATCHED = "MATCHED"
    #: Resolved by a human steward decision; carries the actor in audit.
    MANUALLY_MATCHED = "MANUALLY_MATCHED"
    #: Two or more plausible masters - quarantined, never guessed.
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"
    REJECTED = "REJECTED"

    @property
    def is_usable(self) -> bool:
        return self in {IdentityMatchStatus.MATCHED, IdentityMatchStatus.MANUALLY_MATCHED}


class MatchMethod(StrEnumBase):
    EXACT_SOURCE_ID = "EXACT_SOURCE_ID"
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    PROBABILISTIC = "PROBABILISTIC"
    STEWARD_DECISION = "STEWARD_DECISION"


class ApprovalStatus(StrEnumBase):
    """Generic approval state for costs and finance assumptions."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FinanceScenario(StrEnumBase):
    """plan.md §12.5 requires conservative/base/optimistic ROI propagation."""

    CONSERVATIVE = "CONSERVATIVE"
    BASE = "BASE"
    OPTIMISTIC = "OPTIMISTIC"


# ===========================================================================
# Ingestion
# ===========================================================================


class DatasetType(StrEnumBase):
    """The twelve intake contracts of plan.md §10.1."""

    BRAND_PRODUCT_MASTER = "BRAND_PRODUCT_MASTER"
    CAMPAIGN_EVENT_MASTER = "CAMPAIGN_EVENT_MASTER"
    HCP_MASTER = "HCP_MASTER"
    HCP_CROSSWALK = "HCP_CROSSWALK"
    INVITATIONS = "INVITATIONS"
    ATTENDANCE = "ATTENDANCE"
    RX_MONTHLY = "RX_MONTHLY"
    MARKETING_ACTIVITY = "MARKETING_ACTIVITY"
    EVENT_COST = "EVENT_COST"
    MARKET_FACTORS = "MARKET_FACTORS"
    FINANCE_ASSUMPTIONS = "FINANCE_ASSUMPTIONS"
    CANDIDATE_PROGRAMS = "CANDIDATE_PROGRAMS"

    @property
    def carries_outcomes(self) -> bool:
        """True for datasets whose *contents* are prescription outcomes.

        Used to enforce plan.md §5.5 - a vendor may hold a WRITE grant on these
        but can never be granted READ.
        """
        return self is DatasetType.RX_MONTHLY


class UploadStatus(StrEnumBase):
    """plan.md §10.2 state machine."""

    CREATED = "CREATED"
    UPLOADED = "UPLOADED"
    SCANNING = "SCANNING"
    VALIDATING = "VALIDATING"
    CONFORMING = "CONFORMING"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"
    #: Bytes never arrived before the session expired.
    ABANDONED = "ABANDONED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            UploadStatus.ACCEPTED,
            UploadStatus.PARTIALLY_ACCEPTED,
            UploadStatus.REJECTED,
            UploadStatus.QUARANTINED,
            UploadStatus.ABANDONED,
            UploadStatus.FAILED,
        }

    @property
    def committed_rows(self) -> bool:
        return self in {UploadStatus.ACCEPTED, UploadStatus.PARTIALLY_ACCEPTED}


class IssueSeverity(StrEnumBase):
    """``ERROR`` rejects the row; ``WARNING`` accepts it and flags it.

    ``QUARANTINE`` is distinct from ``ERROR``: the row is structurally valid but
    cannot be conformed yet (an unresolved HCP identifier), so it is parked for a
    steward instead of discarded (plan.md §10.2 step 8).
    """

    ERROR = "ERROR"
    QUARANTINE = "QUARANTINE"
    WARNING = "WARNING"
    INFO = "INFO"


class DataVersionStatus(StrEnumBase):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class FileFormat(StrEnumBase):
    CSV = "CSV"
    XLSX = "XLSX"
    #: Machine-to-machine submissions land as JSON Lines, same contracts.
    JSONL = "JSONL"


# ===========================================================================
# Workflow
# ===========================================================================


class EventWorkflowStatus(StrEnumBase):
    """plan.md §6 workflow status."""

    DRAFT = "DRAFT"
    DATA_PENDING = "DATA_PENDING"
    VALIDATING = "VALIDATING"
    DATA_ISSUES = "DATA_ISSUES"
    READY_FOR_ANALYSIS = "READY_FOR_ANALYSIS"
    ANALYSIS_RUNNING = "ANALYSIS_RUNNING"
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


#: Legal transitions. Anything absent is rejected by the workflow service with a
#: 409 rather than silently applied, so the state machine is data, not prose.
EVENT_WORKFLOW_TRANSITIONS: dict[EventWorkflowStatus, frozenset[EventWorkflowStatus]] = {
    EventWorkflowStatus.DRAFT: frozenset({EventWorkflowStatus.DATA_PENDING}),
    EventWorkflowStatus.DATA_PENDING: frozenset({EventWorkflowStatus.VALIDATING}),
    EventWorkflowStatus.VALIDATING: frozenset(
        {EventWorkflowStatus.DATA_ISSUES, EventWorkflowStatus.READY_FOR_ANALYSIS}
    ),
    EventWorkflowStatus.DATA_ISSUES: frozenset({EventWorkflowStatus.VALIDATING}),
    EventWorkflowStatus.READY_FOR_ANALYSIS: frozenset({EventWorkflowStatus.ANALYSIS_RUNNING}),
    EventWorkflowStatus.ANALYSIS_RUNNING: frozenset(
        {EventWorkflowStatus.ANALYSIS_COMPLETE, EventWorkflowStatus.DATA_ISSUES}
    ),
    EventWorkflowStatus.ANALYSIS_COMPLETE: frozenset(
        {EventWorkflowStatus.UNDER_REVIEW, EventWorkflowStatus.ANALYSIS_RUNNING}
    ),
    EventWorkflowStatus.UNDER_REVIEW: frozenset(
        {EventWorkflowStatus.APPROVED, EventWorkflowStatus.ANALYSIS_COMPLETE}
    ),
    EventWorkflowStatus.APPROVED: frozenset({EventWorkflowStatus.PUBLISHED}),
    # Terminal. A correction creates a *new* run, never a mutation (plan.md §6).
    EventWorkflowStatus.PUBLISHED: frozenset(),
}


class PublicationState(StrEnumBase):
    """Publication scope of an analytical result (docs/PLAN_REVIEW.md F-13)."""

    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ReviewDecision(StrEnumBase):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class ReviewGate(StrEnumBase):
    """Publication requires all three sign-offs (plan.md §6 step 13)."""

    ANALYTICS = "ANALYTICS"
    FINANCE = "FINANCE"
    COMPLIANCE = "COMPLIANCE"


# ===========================================================================
# Analytics and modelling
# ===========================================================================


class OutcomeMetric(StrEnumBase):
    NRX = "NRX"
    TRX = "TRX"


class AnalysisGrain(StrEnumBase):
    """plan.md §3: when HCP-level linkage is unavailable, the product must move
    to a coarser grain *explicitly* rather than pretend."""

    HCP = "HCP"
    ACCOUNT = "ACCOUNT"
    TERRITORY = "TERRITORY"


class AggregationLevel(StrEnumBase):
    """How coarsely a result row was rolled up.

    Deliberately separate from :class:`AnalysisGrain`. That one records how finely
    the *data* could be linked (prescriber, account, territory); this one records
    how far the *answer* was summed. Collapsing the two is how a territory-grain
    estimate ends up presented as an event-level fact.
    """

    EVENT = "EVENT"
    CAMPAIGN = "CAMPAIGN"
    BRAND = "BRAND"
    TOPIC = "TOPIC"
    REGION = "REGION"
    FORMAT = "FORMAT"
    PORTFOLIO = "PORTFOLIO"


class ControlStrategy(StrEnumBase):
    """docs/PLAN_REVIEW.md F-9 - never auto-downgraded, always displayed."""

    INVITED_NON_ATTENDEE = "INVITED_NON_ATTENDEE"
    TARGET_UNIVERSE = "TARGET_UNIVERSE"
    SYNTHETIC_CONTROL_POOL = "SYNTHETIC_CONTROL_POOL"

    @property
    def max_evidence_grade(self) -> EvidenceGrade:
        if self is ControlStrategy.INVITED_NON_ATTENDEE:
            return EvidenceGrade.STRONG
        if self is ControlStrategy.TARGET_UNIVERSE:
            return EvidenceGrade.MODERATE
        return EvidenceGrade.DIRECTIONAL


class EstimatorKind(StrEnumBase):
    """docs/PLAN_REVIEW.md F-10 - the primary is cohort-time ATT, TWFE is a
    robustness diagnostic, not the headline."""

    COHORT_TIME_ATT = "COHORT_TIME_ATT"
    TWFE_DID = "TWFE_DID"


class ExclusionReason(StrEnumBase):
    """Every funnel drop-off has a stored, displayable reason (plan.md §12.1)."""

    NOT_INVITED = "NOT_INVITED"
    INELIGIBLE_SPECIALTY = "INELIGIBLE_SPECIALTY"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    IDENTITY_AMBIGUOUS = "IDENTITY_AMBIGUOUS"
    INSUFFICIENT_PRE_HISTORY = "INSUFFICIENT_PRE_HISTORY"
    INSUFFICIENT_POST_COVERAGE = "INSUFFICIENT_POST_COVERAGE"
    OUTCOME_SUPPRESSED = "OUTCOME_SUPPRESSED"
    EVENT_CANCELLED = "EVENT_CANCELLED"
    OVERLAPPING_EXPOSURE = "OVERLAPPING_EXPOSURE"
    NOT_FIRST_ELIGIBLE_EVENT = "NOT_FIRST_ELIGIBLE_EVENT"
    UNVERIFIED_ATTENDANCE = "UNVERIFIED_ATTENDANCE"
    UNSUPPORTED_MARKET_PERIOD = "UNSUPPORTED_MARKET_PERIOD"
    OUTSIDE_COMMON_SUPPORT = "OUTSIDE_COMMON_SUPPORT"
    NO_MATCH_WITHIN_CALIPER = "NO_MATCH_WITHIN_CALIPER"


class CohortArm(StrEnumBase):
    TREATMENT = "TREATMENT"
    CONTROL = "CONTROL"
    EXCLUDED = "EXCLUDED"


class EvidenceStatus(StrEnumBase):
    """plan.md §12.3: a failed gate yields a *reason*, never a zero lift."""

    ESTIMATED = "ESTIMATED"
    NOT_RELIABLY_ESTIMABLE = "NOT_RELIABLY_ESTIMABLE"


class EvidenceGrade(StrEnumBase):
    """plan.md §12.4 - derived from hard gates, never a learned score."""

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    DIRECTIONAL = "DIRECTIONAL"
    NOT_ESTIMABLE = "NOT_ESTIMABLE"

    @property
    def rank(self) -> int:
        return {"STRONG": 3, "MODERATE": 2, "DIRECTIONAL": 1, "NOT_ESTIMABLE": 0}[self.value]

    @property
    def eligible_for_optimizer(self) -> bool:
        """plan.md §12.4: directional results are excluded from optimization by
        default."""
        return self.rank >= EvidenceGrade.MODERATE.rank


class EvidenceGate(StrEnumBase):
    """The named gates of plan.md §12.3. Each one is stored pass/fail with its
    measured value, so "why is this not estimable" is answerable."""

    MIN_TREATED_SAMPLE = "MIN_TREATED_SAMPLE"
    MIN_CONTROL_SAMPLE = "MIN_CONTROL_SAMPLE"
    OUTCOME_COVERAGE = "OUTCOME_COVERAGE"
    COVARIATE_BALANCE = "COVARIATE_BALANCE"
    PROPENSITY_OVERLAP = "PROPENSITY_OVERLAP"
    MATCHED_RETENTION = "MATCHED_RETENTION"
    PARALLEL_PRE_TREND = "PARALLEL_PRE_TREND"
    PLACEBO_NULL = "PLACEBO_NULL"
    SENSITIVITY_STABILITY = "SENSITIVITY_STABILITY"
    CONTAMINATION = "CONTAMINATION"

    @property
    def is_critical(self) -> bool:
        """Critical gate failure forces ``NOT_RELIABLY_ESTIMABLE``."""
        return self in {
            EvidenceGate.MIN_TREATED_SAMPLE,
            EvidenceGate.MIN_CONTROL_SAMPLE,
            EvidenceGate.OUTCOME_COVERAGE,
            EvidenceGate.COVARIATE_BALANCE,
            EvidenceGate.PROPENSITY_OVERLAP,
            EvidenceGate.PARALLEL_PRE_TREND,
        }


class SensitivityTest(StrEnumBase):
    PLACEBO_PRE_PERIOD = "PLACEBO_PRE_PERIOD"
    ALTERNATE_CALIPER = "ALTERNATE_CALIPER"
    ALTERNATE_CONTROL_RATIO = "ALTERNATE_CONTROL_RATIO"
    ALTERNATE_POST_WINDOW = "ALTERNATE_POST_WINDOW"
    ALTERNATE_CONTROL_DEFINITION = "ALTERNATE_CONTROL_DEFINITION"
    TWFE_CROSSCHECK = "TWFE_CROSSCHECK"
    LEAVE_ONE_MONTH_OUT = "LEAVE_ONE_MONTH_OUT"
    UNMEASURED_CONFOUNDER_BOUND = "UNMEASURED_CONFOUNDER_BOUND"


class ModelKind(StrEnumBase):
    """The four models of docs/PLAN_REVIEW.md F-1.

    Note the absence of the causal estimator: it is an estimator applied to a
    versioned *specification*, not a trained model, so it never enters the
    champion/challenger lifecycle.
    """

    #: M1 - attendance propensity, used only to build comparable cohorts.
    PROPENSITY = "PROPENSITY"
    #: M3 - the forward-looking impact forecaster. The "predict the future" model.
    FUTURE_IMPACT = "FUTURE_IMPACT"
    #: M4 - verified-attendance/reach forecaster for proposed designs.
    ATTENDANCE_FORECAST = "ATTENDANCE_FORECAST"


class ModelLifecycleState(StrEnumBase):
    """plan.md §12.8 lifecycle. A failed challenger leaves the champion active."""

    DRAFT = "DRAFT"
    TRAINING = "TRAINING"
    VALIDATING = "VALIDATING"
    CHALLENGER = "CHALLENGER"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


MODEL_LIFECYCLE_TRANSITIONS: dict[ModelLifecycleState, frozenset[ModelLifecycleState]] = {
    ModelLifecycleState.DRAFT: frozenset({ModelLifecycleState.TRAINING}),
    ModelLifecycleState.TRAINING: frozenset(
        {ModelLifecycleState.VALIDATING, ModelLifecycleState.REJECTED}
    ),
    ModelLifecycleState.VALIDATING: frozenset(
        {ModelLifecycleState.CHALLENGER, ModelLifecycleState.REJECTED}
    ),
    ModelLifecycleState.CHALLENGER: frozenset(
        {ModelLifecycleState.PENDING_APPROVAL, ModelLifecycleState.REJECTED}
    ),
    ModelLifecycleState.PENDING_APPROVAL: frozenset(
        {ModelLifecycleState.ACTIVE, ModelLifecycleState.REJECTED}
    ),
    ModelLifecycleState.ACTIVE: frozenset({ModelLifecycleState.RETIRED}),
    ModelLifecycleState.REJECTED: frozenset(),
    ModelLifecycleState.RETIRED: frozenset(),
}


class RunStatus(StrEnumBase):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    #: Bounded retries exhausted (plan.md §14).
    DEAD_LETTER = "DEAD_LETTER"


class RunKind(StrEnumBase):
    FILE_VALIDATION = "FILE_VALIDATION"
    CONFORMANCE = "CONFORMANCE"
    DATA_VERSION_PUBLISH = "DATA_VERSION_PUBLISH"
    COHORT_BUILD = "COHORT_BUILD"
    PROPENSITY_TRAIN = "PROPENSITY_TRAIN"
    PROPENSITY_SCORE = "PROPENSITY_SCORE"
    MATCHING = "MATCHING"
    CAUSAL_ESTIMATE = "CAUSAL_ESTIMATE"
    SENSITIVITY_SUITE = "SENSITIVITY_SUITE"
    ROI_CALCULATION = "ROI_CALCULATION"
    FORECAST_TRAIN = "FORECAST_TRAIN"
    FORECAST_SCORE = "FORECAST_SCORE"
    BUDGET_OPTIMIZE = "BUDGET_OPTIMIZE"
    AI_SUMMARY_PRECOMPUTE = "AI_SUMMARY_PRECOMPUTE"
    SYNTHETIC_GENERATE = "SYNTHETIC_GENERATE"


class FailureCategory(StrEnumBase):
    """Coarse cause, for the Data & Model Health dashboard (plan.md §7.7)."""

    INPUT_DATA = "INPUT_DATA"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    CONFIGURATION = "CONFIGURATION"
    INTERNAL = "INTERNAL"


# ===========================================================================
# Forecasting, simulation and optimization
# ===========================================================================


class ForecastMode(StrEnumBase):
    """The three-state forecast of docs/PLAN_REVIEW.md F-1.

    ``OUT_OF_SUPPORT`` returns no number at all - it names the offending features
    and what data would fix it.
    """

    MODEL = "MODEL"
    POOLED = "POOLED"
    OUT_OF_SUPPORT = "OUT_OF_SUPPORT"


class ScenarioStatus(StrEnumBase):
    """plan.md §7.5: scenarios are drafts until explicitly saved, and no
    optimizer output ever approves spending."""

    DRAFT = "DRAFT"
    SAVED = "SAVED"
    ARCHIVED = "ARCHIVED"


class OptimizerStatus(StrEnumBase):
    OPTIMAL = "OPTIMAL"
    FEASIBLE_SUBOPTIMAL = "FEASIBLE_SUBOPTIMAL"
    INFEASIBLE = "INFEASIBLE"
    UNBOUNDED = "UNBOUNDED"
    TIME_LIMIT = "TIME_LIMIT"
    FAILED = "FAILED"


class ConstraintKind(StrEnumBase):
    TOTAL_BUDGET = "TOTAL_BUDGET"
    REGION_MIN = "REGION_MIN"
    REGION_MAX = "REGION_MAX"
    TOPIC_MIN = "TOPIC_MIN"
    TOPIC_MAX = "TOPIC_MAX"
    FORMAT_MIN = "FORMAT_MIN"
    FORMAT_MAX = "FORMAT_MAX"
    BRAND_MIN = "BRAND_MIN"
    BRAND_MAX = "BRAND_MAX"
    MAX_PROGRAMS = "MAX_PROGRAMS"
    OPERATIONAL_CAPACITY = "OPERATIONAL_CAPACITY"
    MAX_CONCENTRATION = "MAX_CONCENTRATION"
    EXPLORATION_BUDGET = "EXPLORATION_BUDGET"


# ===========================================================================
# AI Insights
# ===========================================================================


class AiIntent(StrEnumBase):
    """The allowlist (plan.md §7.6). Anything not on this list is refused before
    any retrieval happens."""

    EXPLAIN_EVENT_EVIDENCE = "EXPLAIN_EVENT_EVIDENCE"
    COMPARE_EVENT_CATEGORIES = "COMPARE_EVENT_CATEGORIES"
    SUMMARIZE_STRONG_EVIDENCE = "SUMMARIZE_STRONG_EVIDENCE"
    EXPLAIN_DATA_HEALTH_WARNING = "EXPLAIN_DATA_HEALTH_WARNING"
    NARRATE_BUDGET_TRADEOFFS = "NARRATE_BUDGET_TRADEOFFS"
    EXPLAIN_PORTFOLIO_SUMMARY = "EXPLAIN_PORTFOLIO_SUMMARY"
    EXPLAIN_SIMULATION = "EXPLAIN_SIMULATION"


class AiRefusalReason(StrEnumBase):
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    #: plan.md §3/§15 - the hard compliance refusal.
    HCP_TARGETING = "HCP_TARGETING"
    PATIENT_LEVEL_REQUEST = "PATIENT_LEVEL_REQUEST"
    CROSS_TENANT_REQUEST = "CROSS_TENANT_REQUEST"
    NO_AUTHORIZED_EVIDENCE = "NO_AUTHORIZED_EVIDENCE"
    PROMPT_INJECTION_SUSPECTED = "PROMPT_INJECTION_SUSPECTED"
    RATE_LIMITED = "RATE_LIMITED"


class AiAnswerMode(StrEnumBase):
    LLM = "LLM"
    #: plan.md §0/§7.6 - deterministic template, works with no key and offline.
    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
    REFUSED = "REFUSED"


# ===========================================================================
# Audit
# ===========================================================================


class AuditAction(StrEnumBase):
    LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TENANT_CREATED = "TENANT_CREATED"
    TENANT_STATUS_CHANGED = "TENANT_STATUS_CHANGED"
    TENANT_CONFIG_CHANGED = "TENANT_CONFIG_CHANGED"
    USER_INVITED = "USER_INVITED"
    INVITATION_ACCEPTED = "INVITATION_ACCEPTED"
    INVITATION_REVOKED = "INVITATION_REVOKED"
    MEMBERSHIP_CHANGED = "MEMBERSHIP_CHANGED"
    #: A vendor's dataset access changed. Separate from RECORD_CREATED/RECORD_UPDATED because
    #: this is the pair an auditor asks for by name - "who authorised this agency to submit
    #: prescription data, and when was it withdrawn" - and a generic record event buried among
    #: thousands of brand edits does not answer that question in one query.
    VENDOR_GRANT_GRANTED = "VENDOR_GRANT_GRANTED"
    VENDOR_GRANT_REVOKED = "VENDOR_GRANT_REVOKED"
    RECORD_CREATED = "RECORD_CREATED"
    RECORD_UPDATED = "RECORD_UPDATED"
    RECORD_DEACTIVATED = "RECORD_DEACTIVATED"
    UPLOAD_CREATED = "UPLOAD_CREATED"
    UPLOAD_COMPLETED = "UPLOAD_COMPLETED"
    UPLOAD_REJECTED = "UPLOAD_REJECTED"
    MAPPING_DECIDED = "MAPPING_DECIDED"
    DATA_VERSION_PUBLISHED = "DATA_VERSION_PUBLISHED"
    ANALYSIS_RUN_STARTED = "ANALYSIS_RUN_STARTED"
    ANALYSIS_RUN_COMPLETED = "ANALYSIS_RUN_COMPLETED"
    RESULT_SUBMITTED_FOR_REVIEW = "RESULT_SUBMITTED_FOR_REVIEW"
    REVIEW_DECISION_RECORDED = "REVIEW_DECISION_RECORDED"
    RESULT_PUBLISHED = "RESULT_PUBLISHED"
    MODEL_SUBMITTED = "MODEL_SUBMITTED"
    MODEL_ACTIVATED = "MODEL_ACTIVATED"
    MODEL_ROLLED_BACK = "MODEL_ROLLED_BACK"
    FINANCE_ASSUMPTION_APPROVED = "FINANCE_ASSUMPTION_APPROVED"
    SCENARIO_SAVED = "SCENARIO_SAVED"
    EXPORT_GENERATED = "EXPORT_GENERATED"
    OBJECT_DOWNLOAD_AUTHORIZED = "OBJECT_DOWNLOAD_AUTHORIZED"
    AI_QUERY_ANSWERED = "AI_QUERY_ANSWERED"
    AI_QUERY_REFUSED = "AI_QUERY_REFUSED"
    RETENTION_DELETION_EXECUTED = "RETENTION_DELETION_EXECUTED"


class AuditOutcome(StrEnumBase):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"


#: Every enum that must exist as a PostgreSQL type. The initial migration
#: iterates this list, so adding an enum above is the only step required.
PG_ENUMS: tuple[type[StrEnumBase], ...] = (
    TenantStatus,
    Role,
    MembershipStatus,
    UserStatus,
    InvitationStatus,
    AuthProviderKind,
    VendorStatus,
    DatasetAccess,
    EventStatus,
    EventFormat,
    CampaignStatus,
    TaxonomyKind,
    InvitationChannel,
    AttendanceStatus,
    AttendanceVerificationSource,
    IdentityMatchStatus,
    MatchMethod,
    ApprovalStatus,
    FinanceScenario,
    DatasetType,
    UploadStatus,
    IssueSeverity,
    DataVersionStatus,
    FileFormat,
    EventWorkflowStatus,
    PublicationState,
    ReviewDecision,
    ReviewGate,
    OutcomeMetric,
    AnalysisGrain,
    AggregationLevel,
    ControlStrategy,
    EstimatorKind,
    ExclusionReason,
    CohortArm,
    EvidenceStatus,
    EvidenceGrade,
    EvidenceGate,
    SensitivityTest,
    ModelKind,
    ModelLifecycleState,
    RunStatus,
    RunKind,
    FailureCategory,
    ForecastMode,
    ScenarioStatus,
    OptimizerStatus,
    ConstraintKind,
    AiIntent,
    AiRefusalReason,
    AiAnswerMode,
    AuditAction,
    AuditOutcome,
)
