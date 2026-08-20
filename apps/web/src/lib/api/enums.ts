/**
 * TypeScript mirror of `packages/core/src/speaker_roi_core/enums.py`.
 *
 * GENERATED-COMPATIBLE — when the OpenAPI generator lands it will emit the same
 * string-literal unions. This file is hand-written only because the frontend
 * shipped first; the shape is chosen so the swap is a file replacement, not a
 * refactor. Two rules keep that true:
 *
 *   1. Every enum is a frozen object + a union type of the same name. Generated
 *      clients emit exactly this pair, so imports do not change.
 *   2. Behaviour that exists as a Python `@property` (`is_terminal`,
 *      `max_evidence_grade`, …) is exported here as a standalone function or
 *      lookup table, never as a method, because a generated union has no
 *      methods. Those helpers live below the enum blocks and are the only part
 *      that survives regeneration.
 *
 * If you change a value here, change it in `enums.py` in the same commit. The
 * values are UPPER_SNAKE because they appear verbatim in audit rows and CSV
 * exports on both sides of the wire.
 */

/* ===========================================================================
 * Tenancy, identity and access
 * ======================================================================== */

export const TenantStatus = {
  PENDING_ONBOARDING: 'PENDING_ONBOARDING',
  ACTIVE: 'ACTIVE',
  SUSPENDED: 'SUSPENDED',
  /** Read-only wind-down. Data retained, no new writes accepted. */
  ARCHIVED: 'ARCHIVED',
} as const;
export type TenantStatus = (typeof TenantStatus)[keyof typeof TenantStatus];

export const Role = {
  PLATFORM_ADMIN: 'PLATFORM_ADMIN',
  PHARMA_ADMIN: 'PHARMA_ADMIN',
  VENDOR_CONTRIBUTOR: 'VENDOR_CONTRIBUTOR',
  DATA_STEWARD: 'DATA_STEWARD',
  ANALYTICS_LEAD: 'ANALYTICS_LEAD',
  FINANCE_REVIEWER: 'FINANCE_REVIEWER',
  COMPLIANCE_REVIEWER: 'COMPLIANCE_REVIEWER',
  BRAND_MANAGER: 'BRAND_MANAGER',
  EXECUTIVE_VIEWER: 'EXECUTIVE_VIEWER',
} as const;
export type Role = (typeof Role)[keyof typeof Role];

export const MembershipStatus = {
  ACTIVE: 'ACTIVE',
  SUSPENDED: 'SUSPENDED',
  EXPIRED: 'EXPIRED',
} as const;
export type MembershipStatus = (typeof MembershipStatus)[keyof typeof MembershipStatus];

export const UserStatus = {
  INVITED: 'INVITED',
  ACTIVE: 'ACTIVE',
  DISABLED: 'DISABLED',
  LOCKED: 'LOCKED',
} as const;
export type UserStatus = (typeof UserStatus)[keyof typeof UserStatus];

export const InvitationStatus = {
  PENDING: 'PENDING',
  ACCEPTED: 'ACCEPTED',
  EXPIRED: 'EXPIRED',
  REVOKED: 'REVOKED',
} as const;
export type InvitationStatus = (typeof InvitationStatus)[keyof typeof InvitationStatus];

/** docs/PLAN_REVIEW.md F-3 — both are real implementations, neither is a mock. */
export const AuthProviderKind = {
  LOCAL: 'LOCAL',
  OIDC: 'OIDC',
} as const;
export type AuthProviderKind = (typeof AuthProviderKind)[keyof typeof AuthProviderKind];

export const VendorStatus = {
  ACTIVE: 'ACTIVE',
  SUSPENDED: 'SUSPENDED',
  TERMINATED: 'TERMINATED',
} as const;
export type VendorStatus = (typeof VendorStatus)[keyof typeof VendorStatus];

/** Directional grant (F-8): an Rx supplier writes outcomes it may never read. */
export const DatasetAccess = {
  WRITE: 'WRITE',
  READ: 'READ',
  READ_WRITE: 'READ_WRITE',
} as const;
export type DatasetAccess = (typeof DatasetAccess)[keyof typeof DatasetAccess];

/* ===========================================================================
 * Commercial hierarchy
 * ======================================================================== */

export const EventStatus = {
  PROPOSED: 'PROPOSED',
  SCHEDULED: 'SCHEDULED',
  COMPLETED: 'COMPLETED',
  CANCELLED: 'CANCELLED',
} as const;
export type EventStatus = (typeof EventStatus)[keyof typeof EventStatus];

export const EventFormat = {
  IN_PERSON: 'IN_PERSON',
  VIRTUAL: 'VIRTUAL',
  HYBRID: 'HYBRID',
  ROUNDTABLE: 'ROUNDTABLE',
  ON_DEMAND: 'ON_DEMAND',
} as const;
export type EventFormat = (typeof EventFormat)[keyof typeof EventFormat];

export const CampaignStatus = {
  DRAFT: 'DRAFT',
  ACTIVE: 'ACTIVE',
  COMPLETED: 'COMPLETED',
  CANCELLED: 'CANCELLED',
} as const;
export type CampaignStatus = (typeof CampaignStatus)[keyof typeof CampaignStatus];

export const TaxonomyKind = {
  REGION: 'REGION',
  TOPIC: 'TOPIC',
  SPECIALTY: 'SPECIALTY',
  PRACTICE_TYPE: 'PRACTICE_TYPE',
  HCP_SEGMENT: 'HCP_SEGMENT',
  COST_CATEGORY: 'COST_CATEGORY',
  MARKETING_CHANNEL: 'MARKETING_CHANNEL',
  THERAPEUTIC_AREA: 'THERAPEUTIC_AREA',
} as const;
export type TaxonomyKind = (typeof TaxonomyKind)[keyof typeof TaxonomyKind];

export const InvitationChannel = {
  EMAIL: 'EMAIL',
  REP: 'REP',
  PORTAL: 'PORTAL',
  PHONE: 'PHONE',
  OTHER: 'OTHER',
} as const;
export type InvitationChannel = (typeof InvitationChannel)[keyof typeof InvitationChannel];

export const AttendanceStatus = {
  NOT_REGISTERED: 'NOT_REGISTERED',
  REGISTERED: 'REGISTERED',
  WAITLISTED: 'WAITLISTED',
  CANCELLED: 'CANCELLED',
  NO_SHOW: 'NO_SHOW',
  ATTENDED: 'ATTENDED',
} as const;
export type AttendanceStatus = (typeof AttendanceStatus)[keyof typeof AttendanceStatus];

export const AttendanceVerificationSource = {
  BADGE_SCAN: 'BADGE_SCAN',
  SIGN_IN_SHEET: 'SIGN_IN_SHEET',
  WEBINAR_PLATFORM_LOG: 'WEBINAR_PLATFORM_LOG',
  VENDOR_ATTESTATION: 'VENDOR_ATTESTATION',
  UNVERIFIED: 'UNVERIFIED',
} as const;
export type AttendanceVerificationSource =
  (typeof AttendanceVerificationSource)[keyof typeof AttendanceVerificationSource];

export const IdentityMatchStatus = {
  MATCHED: 'MATCHED',
  MANUALLY_MATCHED: 'MANUALLY_MATCHED',
  AMBIGUOUS: 'AMBIGUOUS',
  UNMATCHED: 'UNMATCHED',
  REJECTED: 'REJECTED',
} as const;
export type IdentityMatchStatus = (typeof IdentityMatchStatus)[keyof typeof IdentityMatchStatus];

export const MatchMethod = {
  EXACT_SOURCE_ID: 'EXACT_SOURCE_ID',
  DETERMINISTIC_RULE: 'DETERMINISTIC_RULE',
  PROBABILISTIC: 'PROBABILISTIC',
  STEWARD_DECISION: 'STEWARD_DECISION',
} as const;
export type MatchMethod = (typeof MatchMethod)[keyof typeof MatchMethod];

export const ApprovalStatus = {
  DRAFT: 'DRAFT',
  SUBMITTED: 'SUBMITTED',
  APPROVED: 'APPROVED',
  REJECTED: 'REJECTED',
} as const;
export type ApprovalStatus = (typeof ApprovalStatus)[keyof typeof ApprovalStatus];

export const FinanceScenario = {
  CONSERVATIVE: 'CONSERVATIVE',
  BASE: 'BASE',
  OPTIMISTIC: 'OPTIMISTIC',
} as const;
export type FinanceScenario = (typeof FinanceScenario)[keyof typeof FinanceScenario];

/* ===========================================================================
 * Ingestion
 * ======================================================================== */

export const DatasetType = {
  BRAND_PRODUCT_MASTER: 'BRAND_PRODUCT_MASTER',
  CAMPAIGN_EVENT_MASTER: 'CAMPAIGN_EVENT_MASTER',
  HCP_MASTER: 'HCP_MASTER',
  HCP_CROSSWALK: 'HCP_CROSSWALK',
  INVITATIONS: 'INVITATIONS',
  ATTENDANCE: 'ATTENDANCE',
  RX_MONTHLY: 'RX_MONTHLY',
  MARKETING_ACTIVITY: 'MARKETING_ACTIVITY',
  EVENT_COST: 'EVENT_COST',
  MARKET_FACTORS: 'MARKET_FACTORS',
  FINANCE_ASSUMPTIONS: 'FINANCE_ASSUMPTIONS',
  CANDIDATE_PROGRAMS: 'CANDIDATE_PROGRAMS',
} as const;
export type DatasetType = (typeof DatasetType)[keyof typeof DatasetType];

export const UploadStatus = {
  CREATED: 'CREATED',
  UPLOADED: 'UPLOADED',
  SCANNING: 'SCANNING',
  VALIDATING: 'VALIDATING',
  CONFORMING: 'CONFORMING',
  ACCEPTED: 'ACCEPTED',
  PARTIALLY_ACCEPTED: 'PARTIALLY_ACCEPTED',
  REJECTED: 'REJECTED',
  QUARANTINED: 'QUARANTINED',
  ABANDONED: 'ABANDONED',
  FAILED: 'FAILED',
} as const;
export type UploadStatus = (typeof UploadStatus)[keyof typeof UploadStatus];

export const IssueSeverity = {
  ERROR: 'ERROR',
  QUARANTINE: 'QUARANTINE',
  WARNING: 'WARNING',
  INFO: 'INFO',
} as const;
export type IssueSeverity = (typeof IssueSeverity)[keyof typeof IssueSeverity];

export const DataVersionStatus = {
  DRAFT: 'DRAFT',
  PUBLISHED: 'PUBLISHED',
  SUPERSEDED: 'SUPERSEDED',
} as const;
export type DataVersionStatus = (typeof DataVersionStatus)[keyof typeof DataVersionStatus];

export const FileFormat = {
  CSV: 'CSV',
  XLSX: 'XLSX',
  JSONL: 'JSONL',
} as const;
export type FileFormat = (typeof FileFormat)[keyof typeof FileFormat];

/* ===========================================================================
 * Workflow
 * ======================================================================== */

export const EventWorkflowStatus = {
  DRAFT: 'DRAFT',
  DATA_PENDING: 'DATA_PENDING',
  VALIDATING: 'VALIDATING',
  DATA_ISSUES: 'DATA_ISSUES',
  READY_FOR_ANALYSIS: 'READY_FOR_ANALYSIS',
  ANALYSIS_RUNNING: 'ANALYSIS_RUNNING',
  ANALYSIS_COMPLETE: 'ANALYSIS_COMPLETE',
  UNDER_REVIEW: 'UNDER_REVIEW',
  APPROVED: 'APPROVED',
  PUBLISHED: 'PUBLISHED',
} as const;
export type EventWorkflowStatus = (typeof EventWorkflowStatus)[keyof typeof EventWorkflowStatus];

export const PublicationState = {
  DRAFT: 'DRAFT',
  UNDER_REVIEW: 'UNDER_REVIEW',
  APPROVED: 'APPROVED',
  PUBLISHED: 'PUBLISHED',
  SUPERSEDED: 'SUPERSEDED',
} as const;
export type PublicationState = (typeof PublicationState)[keyof typeof PublicationState];

export const ReviewDecision = {
  APPROVED: 'APPROVED',
  REJECTED: 'REJECTED',
  CHANGES_REQUESTED: 'CHANGES_REQUESTED',
} as const;
export type ReviewDecision = (typeof ReviewDecision)[keyof typeof ReviewDecision];

export const ReviewGate = {
  ANALYTICS: 'ANALYTICS',
  FINANCE: 'FINANCE',
  COMPLIANCE: 'COMPLIANCE',
} as const;
export type ReviewGate = (typeof ReviewGate)[keyof typeof ReviewGate];

/* ===========================================================================
 * Analytics and modelling
 * ======================================================================== */

export const OutcomeMetric = {
  NRX: 'NRX',
  TRX: 'TRX',
} as const;
export type OutcomeMetric = (typeof OutcomeMetric)[keyof typeof OutcomeMetric];

export const AnalysisGrain = {
  HCP: 'HCP',
  ACCOUNT: 'ACCOUNT',
  TERRITORY: 'TERRITORY',
} as const;
export type AnalysisGrain = (typeof AnalysisGrain)[keyof typeof AnalysisGrain];

/** F-9 — never auto-downgraded, always displayed next to the estimate. */
export const ControlStrategy = {
  INVITED_NON_ATTENDEE: 'INVITED_NON_ATTENDEE',
  TARGET_UNIVERSE: 'TARGET_UNIVERSE',
  SYNTHETIC_CONTROL_POOL: 'SYNTHETIC_CONTROL_POOL',
} as const;
export type ControlStrategy = (typeof ControlStrategy)[keyof typeof ControlStrategy];

export const EstimatorKind = {
  COHORT_TIME_ATT: 'COHORT_TIME_ATT',
  TWFE_DID: 'TWFE_DID',
} as const;
export type EstimatorKind = (typeof EstimatorKind)[keyof typeof EstimatorKind];

export const ExclusionReason = {
  NOT_INVITED: 'NOT_INVITED',
  INELIGIBLE_SPECIALTY: 'INELIGIBLE_SPECIALTY',
  IDENTITY_UNRESOLVED: 'IDENTITY_UNRESOLVED',
  IDENTITY_AMBIGUOUS: 'IDENTITY_AMBIGUOUS',
  INSUFFICIENT_PRE_HISTORY: 'INSUFFICIENT_PRE_HISTORY',
  INSUFFICIENT_POST_COVERAGE: 'INSUFFICIENT_POST_COVERAGE',
  OUTCOME_SUPPRESSED: 'OUTCOME_SUPPRESSED',
  EVENT_CANCELLED: 'EVENT_CANCELLED',
  OVERLAPPING_EXPOSURE: 'OVERLAPPING_EXPOSURE',
  NOT_FIRST_ELIGIBLE_EVENT: 'NOT_FIRST_ELIGIBLE_EVENT',
  UNVERIFIED_ATTENDANCE: 'UNVERIFIED_ATTENDANCE',
  UNSUPPORTED_MARKET_PERIOD: 'UNSUPPORTED_MARKET_PERIOD',
  OUTSIDE_COMMON_SUPPORT: 'OUTSIDE_COMMON_SUPPORT',
  NO_MATCH_WITHIN_CALIPER: 'NO_MATCH_WITHIN_CALIPER',
} as const;
export type ExclusionReason = (typeof ExclusionReason)[keyof typeof ExclusionReason];

export const CohortArm = {
  TREATMENT: 'TREATMENT',
  CONTROL: 'CONTROL',
  EXCLUDED: 'EXCLUDED',
} as const;
export type CohortArm = (typeof CohortArm)[keyof typeof CohortArm];

/** plan.md §12.3: a failed gate yields a *reason*, never a zero lift. */
export const EvidenceStatus = {
  ESTIMATED: 'ESTIMATED',
  NOT_RELIABLY_ESTIMABLE: 'NOT_RELIABLY_ESTIMABLE',
} as const;
export type EvidenceStatus = (typeof EvidenceStatus)[keyof typeof EvidenceStatus];

/** plan.md §12.4 — derived from hard gates, never a learned score. */
export const EvidenceGrade = {
  STRONG: 'STRONG',
  MODERATE: 'MODERATE',
  DIRECTIONAL: 'DIRECTIONAL',
  NOT_ESTIMABLE: 'NOT_ESTIMABLE',
} as const;
export type EvidenceGrade = (typeof EvidenceGrade)[keyof typeof EvidenceGrade];

export const EvidenceGate = {
  MIN_TREATED_SAMPLE: 'MIN_TREATED_SAMPLE',
  MIN_CONTROL_SAMPLE: 'MIN_CONTROL_SAMPLE',
  OUTCOME_COVERAGE: 'OUTCOME_COVERAGE',
  COVARIATE_BALANCE: 'COVARIATE_BALANCE',
  PROPENSITY_OVERLAP: 'PROPENSITY_OVERLAP',
  MATCHED_RETENTION: 'MATCHED_RETENTION',
  PARALLEL_PRE_TREND: 'PARALLEL_PRE_TREND',
  PLACEBO_NULL: 'PLACEBO_NULL',
  SENSITIVITY_STABILITY: 'SENSITIVITY_STABILITY',
  CONTAMINATION: 'CONTAMINATION',
} as const;
export type EvidenceGate = (typeof EvidenceGate)[keyof typeof EvidenceGate];

export const SensitivityTest = {
  PLACEBO_PRE_PERIOD: 'PLACEBO_PRE_PERIOD',
  ALTERNATE_CALIPER: 'ALTERNATE_CALIPER',
  ALTERNATE_CONTROL_RATIO: 'ALTERNATE_CONTROL_RATIO',
  ALTERNATE_POST_WINDOW: 'ALTERNATE_POST_WINDOW',
  ALTERNATE_CONTROL_DEFINITION: 'ALTERNATE_CONTROL_DEFINITION',
  TWFE_CROSSCHECK: 'TWFE_CROSSCHECK',
  LEAVE_ONE_MONTH_OUT: 'LEAVE_ONE_MONTH_OUT',
  UNMEASURED_CONFOUNDER_BOUND: 'UNMEASURED_CONFOUNDER_BOUND',
} as const;
export type SensitivityTest = (typeof SensitivityTest)[keyof typeof SensitivityTest];

/** F-1: the causal estimator is deliberately absent — it is a versioned spec. */
export const ModelKind = {
  PROPENSITY: 'PROPENSITY',
  FUTURE_IMPACT: 'FUTURE_IMPACT',
  ATTENDANCE_FORECAST: 'ATTENDANCE_FORECAST',
} as const;
export type ModelKind = (typeof ModelKind)[keyof typeof ModelKind];

export const ModelLifecycleState = {
  DRAFT: 'DRAFT',
  TRAINING: 'TRAINING',
  VALIDATING: 'VALIDATING',
  CHALLENGER: 'CHALLENGER',
  PENDING_APPROVAL: 'PENDING_APPROVAL',
  ACTIVE: 'ACTIVE',
  REJECTED: 'REJECTED',
  RETIRED: 'RETIRED',
} as const;
export type ModelLifecycleState = (typeof ModelLifecycleState)[keyof typeof ModelLifecycleState];

export const RunStatus = {
  QUEUED: 'QUEUED',
  RUNNING: 'RUNNING',
  SUCCEEDED: 'SUCCEEDED',
  FAILED: 'FAILED',
  CANCELLED: 'CANCELLED',
  DEAD_LETTER: 'DEAD_LETTER',
} as const;
export type RunStatus = (typeof RunStatus)[keyof typeof RunStatus];

export const RunKind = {
  FILE_VALIDATION: 'FILE_VALIDATION',
  CONFORMANCE: 'CONFORMANCE',
  DATA_VERSION_PUBLISH: 'DATA_VERSION_PUBLISH',
  COHORT_BUILD: 'COHORT_BUILD',
  PROPENSITY_TRAIN: 'PROPENSITY_TRAIN',
  PROPENSITY_SCORE: 'PROPENSITY_SCORE',
  MATCHING: 'MATCHING',
  CAUSAL_ESTIMATE: 'CAUSAL_ESTIMATE',
  SENSITIVITY_SUITE: 'SENSITIVITY_SUITE',
  ROI_CALCULATION: 'ROI_CALCULATION',
  FORECAST_TRAIN: 'FORECAST_TRAIN',
  FORECAST_SCORE: 'FORECAST_SCORE',
  BUDGET_OPTIMIZE: 'BUDGET_OPTIMIZE',
  AI_SUMMARY_PRECOMPUTE: 'AI_SUMMARY_PRECOMPUTE',
  SYNTHETIC_GENERATE: 'SYNTHETIC_GENERATE',
} as const;
export type RunKind = (typeof RunKind)[keyof typeof RunKind];

export const FailureCategory = {
  INPUT_DATA: 'INPUT_DATA',
  INSUFFICIENT_EVIDENCE: 'INSUFFICIENT_EVIDENCE',
  DEPENDENCY_UNAVAILABLE: 'DEPENDENCY_UNAVAILABLE',
  TIMEOUT: 'TIMEOUT',
  CONFIGURATION: 'CONFIGURATION',
  INTERNAL: 'INTERNAL',
} as const;
export type FailureCategory = (typeof FailureCategory)[keyof typeof FailureCategory];

/* ===========================================================================
 * Forecasting, simulation and optimization
 * ======================================================================== */

/** F-1: `OUT_OF_SUPPORT` returns no number at all — it names the blocker. */
export const ForecastMode = {
  MODEL: 'MODEL',
  POOLED: 'POOLED',
  OUT_OF_SUPPORT: 'OUT_OF_SUPPORT',
} as const;
export type ForecastMode = (typeof ForecastMode)[keyof typeof ForecastMode];

export const ScenarioStatus = {
  DRAFT: 'DRAFT',
  SAVED: 'SAVED',
  ARCHIVED: 'ARCHIVED',
} as const;
export type ScenarioStatus = (typeof ScenarioStatus)[keyof typeof ScenarioStatus];

export const OptimizerStatus = {
  OPTIMAL: 'OPTIMAL',
  FEASIBLE_SUBOPTIMAL: 'FEASIBLE_SUBOPTIMAL',
  INFEASIBLE: 'INFEASIBLE',
  UNBOUNDED: 'UNBOUNDED',
  TIME_LIMIT: 'TIME_LIMIT',
  FAILED: 'FAILED',
} as const;
export type OptimizerStatus = (typeof OptimizerStatus)[keyof typeof OptimizerStatus];

export const ConstraintKind = {
  TOTAL_BUDGET: 'TOTAL_BUDGET',
  REGION_MIN: 'REGION_MIN',
  REGION_MAX: 'REGION_MAX',
  TOPIC_MIN: 'TOPIC_MIN',
  TOPIC_MAX: 'TOPIC_MAX',
  FORMAT_MIN: 'FORMAT_MIN',
  FORMAT_MAX: 'FORMAT_MAX',
  BRAND_MIN: 'BRAND_MIN',
  BRAND_MAX: 'BRAND_MAX',
  MAX_PROGRAMS: 'MAX_PROGRAMS',
  OPERATIONAL_CAPACITY: 'OPERATIONAL_CAPACITY',
  MAX_CONCENTRATION: 'MAX_CONCENTRATION',
  EXPLORATION_BUDGET: 'EXPLORATION_BUDGET',
} as const;
export type ConstraintKind = (typeof ConstraintKind)[keyof typeof ConstraintKind];

/* ===========================================================================
 * AI Insights
 * ======================================================================== */

export const AiIntent = {
  EXPLAIN_EVENT_EVIDENCE: 'EXPLAIN_EVENT_EVIDENCE',
  COMPARE_EVENT_CATEGORIES: 'COMPARE_EVENT_CATEGORIES',
  SUMMARIZE_STRONG_EVIDENCE: 'SUMMARIZE_STRONG_EVIDENCE',
  EXPLAIN_DATA_HEALTH_WARNING: 'EXPLAIN_DATA_HEALTH_WARNING',
  NARRATE_BUDGET_TRADEOFFS: 'NARRATE_BUDGET_TRADEOFFS',
  EXPLAIN_PORTFOLIO_SUMMARY: 'EXPLAIN_PORTFOLIO_SUMMARY',
  EXPLAIN_SIMULATION: 'EXPLAIN_SIMULATION',
} as const;
export type AiIntent = (typeof AiIntent)[keyof typeof AiIntent];

export const AiRefusalReason = {
  OUT_OF_SCOPE: 'OUT_OF_SCOPE',
  HCP_TARGETING: 'HCP_TARGETING',
  PATIENT_LEVEL_REQUEST: 'PATIENT_LEVEL_REQUEST',
  CROSS_TENANT_REQUEST: 'CROSS_TENANT_REQUEST',
  NO_AUTHORIZED_EVIDENCE: 'NO_AUTHORIZED_EVIDENCE',
  PROMPT_INJECTION_SUSPECTED: 'PROMPT_INJECTION_SUSPECTED',
  RATE_LIMITED: 'RATE_LIMITED',
} as const;
export type AiRefusalReason = (typeof AiRefusalReason)[keyof typeof AiRefusalReason];

export const AiAnswerMode = {
  LLM: 'LLM',
  DETERMINISTIC_FALLBACK: 'DETERMINISTIC_FALLBACK',
  REFUSED: 'REFUSED',
} as const;
export type AiAnswerMode = (typeof AiAnswerMode)[keyof typeof AiAnswerMode];

/* ===========================================================================
 * Audit
 * ======================================================================== */

export const AuditAction = {
  LOGIN_SUCCEEDED: 'LOGIN_SUCCEEDED',
  LOGIN_FAILED: 'LOGIN_FAILED',
  LOGOUT: 'LOGOUT',
  SESSION_EXPIRED: 'SESSION_EXPIRED',
  REAUTH_REQUIRED: 'REAUTH_REQUIRED',
  PERMISSION_DENIED: 'PERMISSION_DENIED',
  TENANT_CREATED: 'TENANT_CREATED',
  TENANT_STATUS_CHANGED: 'TENANT_STATUS_CHANGED',
  TENANT_CONFIG_CHANGED: 'TENANT_CONFIG_CHANGED',
  USER_INVITED: 'USER_INVITED',
  INVITATION_ACCEPTED: 'INVITATION_ACCEPTED',
  INVITATION_REVOKED: 'INVITATION_REVOKED',
  MEMBERSHIP_CHANGED: 'MEMBERSHIP_CHANGED',
  RECORD_CREATED: 'RECORD_CREATED',
  RECORD_UPDATED: 'RECORD_UPDATED',
  RECORD_DEACTIVATED: 'RECORD_DEACTIVATED',
  UPLOAD_CREATED: 'UPLOAD_CREATED',
  UPLOAD_COMPLETED: 'UPLOAD_COMPLETED',
  UPLOAD_REJECTED: 'UPLOAD_REJECTED',
  MAPPING_DECIDED: 'MAPPING_DECIDED',
  DATA_VERSION_PUBLISHED: 'DATA_VERSION_PUBLISHED',
  ANALYSIS_RUN_STARTED: 'ANALYSIS_RUN_STARTED',
  ANALYSIS_RUN_COMPLETED: 'ANALYSIS_RUN_COMPLETED',
  RESULT_SUBMITTED_FOR_REVIEW: 'RESULT_SUBMITTED_FOR_REVIEW',
  REVIEW_DECISION_RECORDED: 'REVIEW_DECISION_RECORDED',
  RESULT_PUBLISHED: 'RESULT_PUBLISHED',
  MODEL_SUBMITTED: 'MODEL_SUBMITTED',
  MODEL_ACTIVATED: 'MODEL_ACTIVATED',
  MODEL_ROLLED_BACK: 'MODEL_ROLLED_BACK',
  FINANCE_ASSUMPTION_APPROVED: 'FINANCE_ASSUMPTION_APPROVED',
  SCENARIO_SAVED: 'SCENARIO_SAVED',
  EXPORT_GENERATED: 'EXPORT_GENERATED',
  OBJECT_DOWNLOAD_AUTHORIZED: 'OBJECT_DOWNLOAD_AUTHORIZED',
  AI_QUERY_ANSWERED: 'AI_QUERY_ANSWERED',
  AI_QUERY_REFUSED: 'AI_QUERY_REFUSED',
  RETENTION_DELETION_EXECUTED: 'RETENTION_DELETION_EXECUTED',
} as const;
export type AuditAction = (typeof AuditAction)[keyof typeof AuditAction];

export const AuditOutcome = {
  SUCCESS: 'SUCCESS',
  FAILURE: 'FAILURE',
  DENIED: 'DENIED',
} as const;
export type AuditOutcome = (typeof AuditOutcome)[keyof typeof AuditOutcome];

/* ===========================================================================
 * Derived behaviour
 *
 * The Python side expresses these as `@property`. A generated TypeScript union
 * cannot carry methods, so they are functions/tables here and survive the
 * OpenAPI swap untouched.
 * ======================================================================== */

/** plan.md §5.3 landing table. Mirrors `_LANDING_ROUTES`. */
export const ROLE_LANDING_ROUTES: Readonly<Record<Role, string>> = {
  PLATFORM_ADMIN: '/platform/companies',
  PHARMA_ADMIN: '/admin/company',
  VENDOR_CONTRIBUTOR: '/vendor/uploads',
  DATA_STEWARD: '/data-health',
  ANALYTICS_LEAD: '/portfolio',
  FINANCE_REVIEWER: '/finance',
  COMPLIANCE_REVIEWER: '/reviews',
  BRAND_MANAGER: '/portfolio',
  EXECUTIVE_VIEWER: '/portfolio',
};

/**
 * Mirrors `ROLE_LANDING_PRECEDENCE`. Most operationally specific first, so a
 * Vendor Contributor who is also an Executive Viewer lands on their upload
 * queue rather than a dashboard they mostly cannot populate.
 */
export const ROLE_LANDING_PRECEDENCE: readonly Role[] = [
  Role.PLATFORM_ADMIN,
  Role.VENDOR_CONTRIBUTOR,
  Role.PHARMA_ADMIN,
  Role.DATA_STEWARD,
  Role.FINANCE_REVIEWER,
  Role.COMPLIANCE_REVIEWER,
  Role.ANALYTICS_LEAD,
  Role.BRAND_MANAGER,
  Role.EXECUTIVE_VIEWER,
];

export function landingRouteForRoles(roles: readonly Role[]): string {
  const winner = ROLE_LANDING_PRECEDENCE.find((r) => roles.includes(r));
  // No membership resolved yet (invited-but-unassigned). The shell renders an
  // explanatory state rather than a blank dashboard.
  return winner ? ROLE_LANDING_ROUTES[winner] : '/no-access';
}

export function isPlatformRole(role: Role): boolean {
  return role === Role.PLATFORM_ADMIN;
}

/** Only a COMPLETED event creates treatment exposure (plan.md §6). */
export function eventCreatesExposure(status: EventStatus): boolean {
  return status === EventStatus.COMPLETED;
}

export function isStrongVerification(source: AttendanceVerificationSource): boolean {
  return (
    source === AttendanceVerificationSource.BADGE_SCAN ||
    source === AttendanceVerificationSource.WEBINAR_PLATFORM_LOG
  );
}

export function isUsableIdentityMatch(status: IdentityMatchStatus): boolean {
  return (
    status === IdentityMatchStatus.MATCHED || status === IdentityMatchStatus.MANUALLY_MATCHED
  );
}

/** True for datasets whose contents *are* prescription outcomes (F-8). */
export function datasetCarriesOutcomes(kind: DatasetType): boolean {
  return kind === DatasetType.RX_MONTHLY;
}

const TERMINAL_UPLOAD_STATUSES: ReadonlySet<UploadStatus> = new Set([
  UploadStatus.ACCEPTED,
  UploadStatus.PARTIALLY_ACCEPTED,
  UploadStatus.REJECTED,
  UploadStatus.QUARANTINED,
  UploadStatus.ABANDONED,
  UploadStatus.FAILED,
]);

export function isTerminalUploadStatus(status: UploadStatus): boolean {
  return TERMINAL_UPLOAD_STATUSES.has(status);
}

export function uploadCommittedRows(status: UploadStatus): boolean {
  return status === UploadStatus.ACCEPTED || status === UploadStatus.PARTIALLY_ACCEPTED;
}

export const EVIDENCE_GRADE_RANK: Readonly<Record<EvidenceGrade, number>> = {
  STRONG: 3,
  MODERATE: 2,
  DIRECTIONAL: 1,
  NOT_ESTIMABLE: 0,
};

/** plan.md §12.4: directional results are excluded from optimization by default. */
export function isOptimizerEligible(grade: EvidenceGrade): boolean {
  return EVIDENCE_GRADE_RANK[grade] >= EVIDENCE_GRADE_RANK.MODERATE;
}

/** F-9 ceiling. Rendered next to the estimate so the design is never implicit. */
export const CONTROL_STRATEGY_MAX_GRADE: Readonly<Record<ControlStrategy, EvidenceGrade>> = {
  INVITED_NON_ATTENDEE: EvidenceGrade.STRONG,
  TARGET_UNIVERSE: EvidenceGrade.MODERATE,
  SYNTHETIC_CONTROL_POOL: EvidenceGrade.DIRECTIONAL,
};

const CRITICAL_GATES: ReadonlySet<EvidenceGate> = new Set([
  EvidenceGate.MIN_TREATED_SAMPLE,
  EvidenceGate.MIN_CONTROL_SAMPLE,
  EvidenceGate.OUTCOME_COVERAGE,
  EvidenceGate.COVARIATE_BALANCE,
  EvidenceGate.PROPENSITY_OVERLAP,
  EvidenceGate.PARALLEL_PRE_TREND,
]);

/** A critical gate failure forces NOT_RELIABLY_ESTIMABLE. */
export function isCriticalGate(gate: EvidenceGate): boolean {
  return CRITICAL_GATES.has(gate);
}

/**
 * Legal workflow transitions (mirrors `EVENT_WORKFLOW_TRANSITIONS`). The UI uses
 * this to decide which action buttons to render; the API still rejects an
 * illegal transition with 409, because a client-side table is not a guard.
 */
export const EVENT_WORKFLOW_TRANSITIONS: Readonly<
  Record<EventWorkflowStatus, readonly EventWorkflowStatus[]>
> = {
  DRAFT: [EventWorkflowStatus.DATA_PENDING],
  DATA_PENDING: [EventWorkflowStatus.VALIDATING],
  VALIDATING: [EventWorkflowStatus.DATA_ISSUES, EventWorkflowStatus.READY_FOR_ANALYSIS],
  DATA_ISSUES: [EventWorkflowStatus.VALIDATING],
  READY_FOR_ANALYSIS: [EventWorkflowStatus.ANALYSIS_RUNNING],
  ANALYSIS_RUNNING: [EventWorkflowStatus.ANALYSIS_COMPLETE, EventWorkflowStatus.DATA_ISSUES],
  ANALYSIS_COMPLETE: [EventWorkflowStatus.UNDER_REVIEW, EventWorkflowStatus.ANALYSIS_RUNNING],
  UNDER_REVIEW: [EventWorkflowStatus.APPROVED, EventWorkflowStatus.ANALYSIS_COMPLETE],
  APPROVED: [EventWorkflowStatus.PUBLISHED],
  // Terminal: a correction creates a *new* run, never a mutation (plan.md §6).
  PUBLISHED: [],
};

export const MODEL_LIFECYCLE_TRANSITIONS: Readonly<
  Record<ModelLifecycleState, readonly ModelLifecycleState[]>
> = {
  DRAFT: [ModelLifecycleState.TRAINING],
  TRAINING: [ModelLifecycleState.VALIDATING, ModelLifecycleState.REJECTED],
  VALIDATING: [ModelLifecycleState.CHALLENGER, ModelLifecycleState.REJECTED],
  CHALLENGER: [ModelLifecycleState.PENDING_APPROVAL, ModelLifecycleState.REJECTED],
  PENDING_APPROVAL: [ModelLifecycleState.ACTIVE, ModelLifecycleState.REJECTED],
  ACTIVE: [ModelLifecycleState.RETIRED],
  REJECTED: [],
  RETIRED: [],
};

/** All roles, in the plan.md §5.2 table order. */
export const ALL_ROLES: readonly Role[] = Object.values(Role);
