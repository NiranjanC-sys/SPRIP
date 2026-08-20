/**
 * Core DTOs.
 *
 * GENERATED-COMPATIBLE — this file is the seam the OpenAPI generator replaces.
 * To keep the swap mechanical:
 *
 *   - Enums live in `./enums.ts` and are only re-exported here. The generator
 *     will not own them; `enums.py` does.
 *   - Every DTO is declared as a zod schema with `z.infer` beside it, so the
 *     runtime guard and the compile-time type cannot drift. When the generator
 *     lands it emits the interfaces and these schemas become the *validation*
 *     layer only — delete the duplicated `export type` lines, keep the schemas.
 *   - Nothing outside `src/lib/api/**` imports a schema. Components import the
 *     type. That is what makes the replacement a one-directory change.
 *
 * Field naming is camelCase: the API serialises with a camel alias generator so
 * the wire format and TypeScript agree without a mapping layer.
 */

import { z } from 'zod';

import {
  AuthProviderKind,
  CampaignStatus,
  ControlStrategy,
  DataVersionStatus,
  DatasetType,
  EstimatorKind,
  EventFormat,
  EventWorkflowStatus,
  EvidenceGate,
  EvidenceGrade,
  EvidenceStatus,
  FailureCategory,
  FileFormat,
  IssueSeverity,
  MembershipStatus,
  ModelKind,
  ModelLifecycleState,
  PublicationState,
  Role,
  RunKind,
  RunStatus,
  TenantStatus,
  UploadStatus,
  UserStatus,
} from './enums';

// One import site for a dashboard: `import { EvidenceGrade, type Kpi } from
// '@/lib/api/types'` resolves both the value and the DTO.
export * from './enums';

/* ===========================================================================
 * Primitives
 * ======================================================================== */

/** Helper: turn a mirrored enum object into a zod union of its values. */
function enumOf<T extends Record<string, string>>(source: T) {
  const values = Object.values(source) as [T[keyof T], ...T[keyof T][]];
  return z.enum(values as unknown as [string, ...string[]]) as unknown as z.ZodType<T[keyof T]>;
}

export const uuidSchema = z.string().uuid();
/** ISO-8601 instant, always UTC on this API. */
export const instantSchema = z.string();
/** `YYYY-MM`, the analytical panel grain. */
export const monthSchema = z.string().regex(/^\d{4}-\d{2}$/);

/**
 * A point estimate with its interval. Every causal number on this API is one of
 * these — a bare float would let a dashboard render a lift without its
 * uncertainty, which plan.md §7.0 forbids.
 */
export const intervalSchema = z.object({
  point: z.number().nullable(),
  lower: z.number().nullable(),
  upper: z.number().nullable(),
  /** e.g. 0.95. Displayed in the tooltip; never assumed. */
  confidenceLevel: z.number().nullable().optional(),
});
export type IntervalValue = z.infer<typeof intervalSchema>;

/**
 * plan.md §14: every displayed analytical number must resolve to this tuple.
 * `LineageChip` renders it verbatim.
 */
export const lineageSchema = z.object({
  tenantId: uuidSchema,
  dataVersion: z.string(),
  runId: z.string().nullable(),
  modelVersion: z.string().nullable(),
  financeVersion: z.string().nullable(),
  /** Set when the number came from a published projection (F-13). */
  publicationState: enumOf(PublicationState).nullable().optional(),
  computedAt: instantSchema.nullable().optional(),
});
export type Lineage = z.infer<typeof lineageSchema>;

/** Cursor pagination (plan.md §13). Offsets are not offered: analytical lists
 *  are re-ranked between requests and offsets silently skip rows. */
export function paginatedSchema<T extends z.ZodTypeAny>(item: T) {
  return z.object({
    items: z.array(item),
    nextCursor: z.string().nullable(),
    /** Optional: some endpoints cannot count cheaply and return null. */
    totalCount: z.number().int().nullable().optional(),
  });
}
export interface Paginated<T> {
  items: T[];
  nextCursor: string | null;
  totalCount?: number | null;
}

/* ===========================================================================
 * Session and identity
 * ======================================================================== */

export const brandScopeSchema = z.object({
  brandId: uuidSchema,
  brandName: z.string(),
  brandCode: z.string(),
});
export type BrandScope = z.infer<typeof brandScopeSchema>;

export const tenantContextSchema = z.object({
  tenantId: uuidSchema,
  tenantCode: z.string(),
  name: z.string(),
  status: enumOf(TenantStatus),
  /** ISO-4217. Drives every currency formatter; there is no browser default. */
  reportingCurrency: z.string(),
  locale: z.string().default('en-US'),
  /** plan.md §11 — every page must show the synthetic badge when this is true. */
  syntheticMode: z.boolean(),
  dataRegion: z.string().nullable().optional(),
  featureFlags: z.record(z.boolean()).default({}),
});
export type TenantContext = z.infer<typeof tenantContextSchema>;

export const membershipSchema = z.object({
  membershipId: uuidSchema,
  tenantId: uuidSchema,
  tenantName: z.string(),
  roles: z.array(enumOf(Role)),
  status: enumOf(MembershipStatus),
  brandScopes: z.array(brandScopeSchema).default([]),
  vendorId: uuidSchema.nullable().optional(),
});
export type Membership = z.infer<typeof membershipSchema>;

export const sessionUserSchema = z.object({
  userId: uuidSchema,
  email: z.string(),
  displayName: z.string(),
  status: enumOf(UserStatus),
  mfaEnrolled: z.boolean().default(false),
  lastLoginAt: instantSchema.nullable().optional(),
});
export type SessionUser = z.infer<typeof sessionUserSchema>;

/**
 * `GET /auth/me`. The authoritative answer to "who is this and what may they
 * see" — resolved from the application database, never from a token claim
 * (F-3). The client treats it as read-only truth.
 */
export const sessionSchema = z.object({
  user: sessionUserSchema,
  /** Roles effective in the active tenant. Platform admins have no tenant. */
  roles: z.array(enumOf(Role)),
  activeTenant: tenantContextSchema.nullable(),
  memberships: z.array(membershipSchema).default([]),
  brandScopes: z.array(brandScopeSchema).default([]),
  authProvider: enumOf(AuthProviderKind),
  /** Absolute session expiry, used to warn before the session dies. */
  expiresAt: instantSchema.nullable().optional(),
  /** True after a step-up auth; sensitive actions check it (plan.md §5.3). */
  reauthenticatedRecently: z.boolean().default(false),
});
export type Session = z.infer<typeof sessionSchema>;

/** Login outcomes the UI must render distinctly (all four are real states). */
export const loginResultSchema = z.discriminatedUnion('outcome', [
  z.object({ outcome: z.literal('AUTHENTICATED'), session: sessionSchema }),
  z.object({
    outcome: z.literal('MFA_REQUIRED'),
    /** Opaque; posted back with the TOTP code. Not a credential. */
    challengeId: z.string(),
  }),
  z.object({ outcome: z.literal('PASSWORD_RESET_REQUIRED'), resetToken: z.string() }),
  z.object({ outcome: z.literal('REDIRECT'), authorizationUrl: z.string() }),
]);
export type LoginResult = z.infer<typeof loginResultSchema>;

export const invitationPreviewSchema = z.object({
  email: z.string(),
  tenantName: z.string(),
  invitedByName: z.string(),
  roles: z.array(enumOf(Role)),
  expiresAt: instantSchema,
  /** Tenant policy may force TOTP enrolment during acceptance. */
  mfaRequired: z.boolean().default(false),
});
export type InvitationPreview = z.infer<typeof invitationPreviewSchema>;

/* ===========================================================================
 * Commercial hierarchy — the reference data filters are built from
 * ======================================================================== */

export const brandSchema = z.object({
  brandId: uuidSchema,
  code: z.string(),
  name: z.string(),
  therapeuticArea: z.string().nullable(),
  active: z.boolean(),
});
export type Brand = z.infer<typeof brandSchema>;

export const campaignSchema = z.object({
  campaignId: uuidSchema,
  brandId: uuidSchema,
  code: z.string(),
  name: z.string(),
  status: enumOf(CampaignStatus),
  startDate: z.string().nullable(),
  endDate: z.string().nullable(),
});
export type Campaign = z.infer<typeof campaignSchema>;

export const taxonomyValueSchema = z.object({
  id: uuidSchema,
  code: z.string(),
  label: z.string(),
  active: z.boolean().default(true),
});
export type TaxonomyValue = z.infer<typeof taxonomyValueSchema>;

/** Everything `FilterBar` needs to populate itself, in one request. */
export const filterOptionsSchema = z.object({
  brands: z.array(brandSchema),
  campaigns: z.array(campaignSchema),
  topics: z.array(taxonomyValueSchema),
  regions: z.array(taxonomyValueSchema),
  formats: z.array(enumOf(EventFormat)),
  /** Inclusive month bounds of the tenant's outcome panel. */
  periodMin: monthSchema.nullable(),
  periodMax: monthSchema.nullable(),
});
export type FilterOptions = z.infer<typeof filterOptionsSchema>;

export const savedViewSchema = z.object({
  savedViewId: uuidSchema,
  name: z.string(),
  scope: z.string(),
  /** Serialised URL query for the page. Replayed verbatim on apply. */
  query: z.string(),
  isShared: z.boolean().default(false),
  createdAt: instantSchema,
});
export type SavedView = z.infer<typeof savedViewSchema>;

/* ===========================================================================
 * Shell services
 * ======================================================================== */

export const freshnessSchema = z.object({
  /** Publication timestamp of the data version the page is reading. */
  dataVersionPublishedAt: instantSchema.nullable(),
  dataVersion: z.string().nullable(),
  dataVersionStatus: enumOf(DataVersionStatus).nullable(),
  /** Feeds behind their expected delivery cadence. Drives the amber state. */
  staleSourceCount: z.number().int().default(0),
  failedJobCount: z.number().int().default(0),
  lastSuccessfulRunAt: instantSchema.nullable().optional(),
});
export type Freshness = z.infer<typeof freshnessSchema>;

export const notificationSchema = z.object({
  notificationId: uuidSchema,
  kind: z.enum(['RUN', 'UPLOAD', 'REVIEW', 'SYSTEM']),
  severity: z.enum(['INFO', 'SUCCESS', 'WARNING', 'ERROR']),
  title: z.string(),
  body: z.string().nullable(),
  href: z.string().nullable(),
  createdAt: instantSchema,
  readAt: instantSchema.nullable(),
});
export type NotificationItem = z.infer<typeof notificationSchema>;

/** Command palette results. `kind` selects the icon; `href` is pre-authorised
 *  by the server, so the palette never renders a link the user cannot open. */
export const searchResultSchema = z.object({
  id: z.string(),
  kind: z.enum(['EVENT', 'CAMPAIGN', 'BRAND', 'UPLOAD', 'RUN', 'SCENARIO', 'PAGE']),
  title: z.string(),
  subtitle: z.string().nullable(),
  href: z.string(),
});
export type SearchResult = z.infer<typeof searchResultSchema>;

/* ===========================================================================
 * Evidence primitives shared across dashboards
 * ======================================================================== */

export const evidenceGateResultSchema = z.object({
  gate: enumOf(EvidenceGate),
  passed: z.boolean(),
  /** The measured statistic, so "why did this fail" is answerable. */
  observedValue: z.number().nullable(),
  threshold: z.number().nullable(),
  isCritical: z.boolean(),
});
export type EvidenceGateResult = z.infer<typeof evidenceGateResultSchema>;

/**
 * The evidence header every analytical object carries. When `status` is
 * `NOT_RELIABLY_ESTIMABLE` there is no number to show — the UI must render
 * `InsufficientEvidenceState` from `failedGates`, not a zero.
 */
export const evidenceSummarySchema = z.object({
  status: enumOf(EvidenceStatus),
  grade: enumOf(EvidenceGrade),
  controlStrategy: enumOf(ControlStrategy),
  /** Required when strategy is TARGET_UNIVERSE (F-9). */
  controlStrategyJustification: z.string().nullable().optional(),
  estimator: enumOf(EstimatorKind).nullable().optional(),
  failedGates: z.array(evidenceGateResultSchema).default([]),
  /** Human-readable reason, present iff status is NOT_RELIABLY_ESTIMABLE. */
  reason: z.string().nullable().optional(),
});
export type EvidenceSummary = z.infer<typeof evidenceSummarySchema>;

/** Unit hints so `KpiCard` formats without hard-coding per-metric rules. */
export const metricUnitSchema = z.enum([
  'COUNT',
  'CURRENCY',
  'PERCENT',
  'RATIO',
  'MULTIPLE',
  'RX',
]);
export type MetricUnit = z.infer<typeof metricUnitSchema>;

/**
 * A KPI as the API returns it. The frontend supplies no numbers of its own —
 * value, unit, comparison and interval all arrive together (plan.md §7.0).
 */
export const kpiSchema = z.object({
  key: z.string(),
  label: z.string(),
  unit: metricUnitSchema,
  value: z.number().nullable(),
  interval: intervalSchema.nullable().optional(),
  /** Same metric over the comparison period; `null` when not comparable. */
  comparisonValue: z.number().nullable().optional(),
  comparisonLabel: z.string().nullable().optional(),
  /** Signed ratio change vs comparison. Sign carries meaning; see `higherIsBetter`. */
  changeRatio: z.number().nullable().optional(),
  /** False for cost-like metrics, so trend colour is never guessed. */
  higherIsBetter: z.boolean().default(true),
  evidence: evidenceSummarySchema.nullable().optional(),
  /** Definition text for the metric tooltip. Authored server-side so the
   *  glossary has one home and exports can reuse it. */
  definition: z.string().nullable().optional(),
  lineage: lineageSchema.nullable().optional(),
});
export type Kpi = z.infer<typeof kpiSchema>;

/**
 * Generic chart payload. Dashboards receive this from the API and pass
 * `series`/`categories` straight into `<Chart>`; no component ever authors the
 * numbers (plan.md §7.0, F-7).
 */
export const chartSeriesSchema = z.object({
  key: z.string(),
  label: z.string(),
  /** Nulls are gaps, not zeros — an unreported month must break the line. */
  values: z.array(z.number().nullable()),
  /** Optional confidence band, aligned index-for-index with `values`. */
  lower: z.array(z.number().nullable()).nullable().optional(),
  upper: z.array(z.number().nullable()).nullable().optional(),
  /** `attendee` / `control` map to the fixed pair; anything else cycles the
   *  categorical palette. */
  role: z.enum(['attendee', 'control', 'category']).default('category'),
});
export type ChartSeries = z.infer<typeof chartSeriesSchema>;

export const chartPayloadSchema = z.object({
  categories: z.array(z.string()),
  series: z.array(chartSeriesSchema),
  unit: metricUnitSchema.nullable().optional(),
  lineage: lineageSchema.nullable().optional(),
});
export type ChartPayload = z.infer<typeof chartPayloadSchema>;

/* ===========================================================================
 * Ingestion
 * ======================================================================== */

export const uploadTemplateSchema = z.object({
  datasetType: enumOf(DatasetType),
  templateVersion: z.string(),
  label: z.string(),
  description: z.string(),
  acceptedFormats: z.array(enumOf(FileFormat)),
  downloadUrl: z.string(),
  dataDictionaryUrl: z.string().nullable(),
  maxBytes: z.number().int(),
  maxRows: z.number().int(),
});
export type UploadTemplate = z.infer<typeof uploadTemplateSchema>;

/** Step 4 of plan.md §10.3 — the client transfers bytes to object storage
 *  itself, so the API hands back a destination rather than accepting the file. */
export const uploadSessionSchema = z.object({
  uploadId: uuidSchema,
  datasetType: enumOf(DatasetType),
  uploadUrl: z.string(),
  method: z.enum(['PUT', 'POST']),
  headers: z.record(z.string()).default({}),
  expiresAt: instantSchema,
});
export type UploadSession = z.infer<typeof uploadSessionSchema>;

/** The immutable receipt (plan.md §21.7). Displayed after every upload. */
export const objectReceiptSchema = z.object({
  bucket: z.string(),
  objectKey: z.string(),
  checksumSha256: z.string(),
  sizeBytes: z.number().int(),
  storedAt: instantSchema,
});
export type ObjectReceipt = z.infer<typeof objectReceiptSchema>;

export const validationIssueSchema = z.object({
  severity: enumOf(IssueSeverity),
  code: z.string(),
  message: z.string(),
  /** Original file row number, preserved through chunked parsing (§10.3). */
  rowNumber: z.number().int().nullable(),
  column: z.string().nullable(),
  occurrences: z.number().int().default(1),
});
export type ValidationIssue = z.infer<typeof validationIssueSchema>;

export const uploadBatchSchema = z.object({
  uploadId: uuidSchema,
  datasetType: enumOf(DatasetType),
  fileName: z.string(),
  fileFormat: enumOf(FileFormat),
  status: enumOf(UploadStatus),
  /** Byte transfer, 0..1. Separate from processing (plan.md §10.3). */
  uploadProgress: z.number().min(0).max(1).nullable(),
  /** Server-side parse/validate/conform, 0..1. */
  processingProgress: z.number().min(0).max(1).nullable(),
  rowsTotal: z.number().int().nullable(),
  rowsAccepted: z.number().int().nullable(),
  rowsRejected: z.number().int().nullable(),
  rowsQuarantined: z.number().int().nullable(),
  issues: z.array(validationIssueSchema).default([]),
  errorReportUrl: z.string().nullable(),
  receipt: objectReceiptSchema.nullable(),
  submittedByName: z.string().nullable(),
  createdAt: instantSchema,
  completedAt: instantSchema.nullable(),
  /** Set when this batch is a correction of an earlier one (§10.3 step 8). */
  correctsUploadId: uuidSchema.nullable().optional(),
});
export type UploadBatch = z.infer<typeof uploadBatchSchema>;

/* ===========================================================================
 * Runs, models, review — shared by Data & Model Health and the review queue
 * ======================================================================== */

export const runSummarySchema = z.object({
  runId: uuidSchema,
  kind: enumOf(RunKind),
  status: enumOf(RunStatus),
  startedAt: instantSchema.nullable(),
  finishedAt: instantSchema.nullable(),
  durationSeconds: z.number().nullable(),
  attempts: z.number().int().default(1),
  failureCategory: enumOf(FailureCategory).nullable(),
  errorMessage: z.string().nullable(),
  dataVersion: z.string().nullable(),
});
export type RunSummary = z.infer<typeof runSummarySchema>;

export const modelVersionSchema = z.object({
  modelVersionId: uuidSchema,
  kind: enumOf(ModelKind),
  version: z.string(),
  state: enumOf(ModelLifecycleState),
  trainedAt: instantSchema.nullable(),
  trainingWindowStart: monthSchema.nullable(),
  trainingWindowEnd: monthSchema.nullable(),
  /** Metric name -> value. Named by the trainer, not hard-coded here. */
  metrics: z.record(z.number()).default({}),
  isChampion: z.boolean().default(false),
});
export type ModelVersion = z.infer<typeof modelVersionSchema>;

export const reviewItemSchema = z.object({
  reviewId: uuidSchema,
  subjectType: z.enum(['EVENT_RESULT', 'FINANCE_ASSUMPTION', 'MODEL_VERSION']),
  subjectId: uuidSchema,
  subjectLabel: z.string(),
  workflowStatus: enumOf(EventWorkflowStatus).nullable(),
  publicationState: enumOf(PublicationState).nullable(),
  submittedAt: instantSchema,
  submittedByName: z.string(),
  /** Gate -> whether this reviewer's sign-off is outstanding. */
  pendingGates: z.array(z.string()).default([]),
  evidence: evidenceSummarySchema.nullable(),
});
export type ReviewItem = z.infer<typeof reviewItemSchema>;

/* ===========================================================================
 * Cross-cutting narrow DTOs used by the shell
 * ======================================================================== */

export const auditNoteSchema = z.object({
  action: z.string(),
  /** Shown in the confirm dialog: "this will be recorded as …" (plan.md §7.0). */
  auditEffect: z.string(),
  requiresReauth: z.boolean().default(false),
});
export type AuditNote = z.infer<typeof auditNoteSchema>;
