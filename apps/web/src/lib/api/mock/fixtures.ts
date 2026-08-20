import {
  AuthProviderKind,
  ControlStrategy,
  DataVersionStatus,
  DatasetType,
  EstimatorKind,
  EventFormat,
  EvidenceGrade,
  EvidenceStatus,
  FileFormat,
  MembershipStatus,
  PublicationState,
  UploadStatus,
  UserStatus,
  type Role,
} from '../enums';
import type {
  FilterOptions,
  Freshness,
  Kpi,
  NotificationItem,
  Paginated,
  SavedView,
  SearchResult,
  Session,
  UploadBatch,
  UploadTemplate,
} from '../types';

/**
 * Fixtures for `NEXT_PUBLIC_API_MOCK=1`.
 *
 * These are *stand-ins for the API*, not dashboard content. plan.md §7.0 bans
 * embedding business numbers in frontend components; this module is the fake
 * server, so it is the one place numbers may exist — the same way a fixture file
 * in a test suite may. Nothing under `src/components/**` imports it, and
 * `npm run check:no-magic-charts` enforces that boundary.
 *
 * Values are deterministic (a small LCG, no Math.random) so a screenshot taken
 * today matches one taken next week and visual review stays meaningful.
 */

const TENANT_ID = '9f2a1c44-0000-4000-8000-000000000001';
const USER_ID = '9f2a1c44-0000-4000-8000-0000000000a1';

/** Deterministic pseudo-random in [0,1). Seeded per series, never global. */
function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

export function buildSession(email: string, roles: Role[]): Session {
  return {
    user: {
      userId: USER_ID,
      email,
      displayName: email
        .split('@')[0]!
        .split(/[._-]/)
        .map((p) => (p ? p[0]!.toUpperCase() + p.slice(1) : p))
        .join(' '),
      status: UserStatus.ACTIVE,
      mfaEnrolled: false,
      lastLoginAt: null,
    },
    roles,
    activeTenant: {
      tenantId: TENANT_ID,
      tenantCode: 'NORTHWIND',
      name: 'Northwind Therapeutics',
      status: 'ACTIVE',
      reportingCurrency: 'USD',
      locale: 'en-US',
      // The demo tenant is synthetic, so every page must carry the badge.
      syntheticMode: true,
      dataRegion: 'eu-west-1',
      featureFlags: {},
    },
    memberships: [
      {
        membershipId: '9f2a1c44-0000-4000-8000-0000000000b1',
        tenantId: TENANT_ID,
        tenantName: 'Northwind Therapeutics',
        roles,
        status: MembershipStatus.ACTIVE,
        brandScopes: [],
        vendorId: null,
      },
      {
        membershipId: '9f2a1c44-0000-4000-8000-0000000000b2',
        tenantId: '9f2a1c44-0000-4000-8000-000000000002',
        tenantName: 'Meridian Biosciences',
        roles,
        status: MembershipStatus.ACTIVE,
        brandScopes: [],
        vendorId: null,
      },
    ],
    brandScopes: [
      { brandId: 'b1000000-0000-4000-8000-000000000001', brandName: 'Cardivex', brandCode: 'CDX' },
      { brandId: 'b1000000-0000-4000-8000-000000000002', brandName: 'Neurolyn', brandCode: 'NRL' },
    ],
    authProvider: AuthProviderKind.LOCAL,
    expiresAt: new Date(Date.now() + 8 * 3600_000).toISOString(),
    reauthenticatedRecently: false,
  };
}

export const freshness: Freshness = {
  dataVersionPublishedAt: new Date(Date.now() - 5 * 3600_000).toISOString(),
  dataVersion: 'dv_2026_07_28',
  dataVersionStatus: DataVersionStatus.PUBLISHED,
  staleSourceCount: 1,
  failedJobCount: 0,
  lastSuccessfulRunAt: new Date(Date.now() - 2 * 3600_000).toISOString(),
};

export const filterOptions: FilterOptions = {
  brands: [
    { brandId: 'b1000000-0000-4000-8000-000000000001', code: 'CDX', name: 'Cardivex', therapeuticArea: 'Cardiology', active: true },
    { brandId: 'b1000000-0000-4000-8000-000000000002', code: 'NRL', name: 'Neurolyn', therapeuticArea: 'Neurology', active: true },
    { brandId: 'b1000000-0000-4000-8000-000000000003', code: 'PLM', name: 'Pulmara', therapeuticArea: 'Respiratory', active: true },
  ],
  campaigns: [
    { campaignId: 'c1000000-0000-4000-8000-000000000001', brandId: 'b1000000-0000-4000-8000-000000000001', code: 'CDX-SPK-H1', name: 'Cardivex Speaker Series H1', status: 'ACTIVE', startDate: '2026-01-01', endDate: '2026-06-30' },
    { campaignId: 'c1000000-0000-4000-8000-000000000002', brandId: 'b1000000-0000-4000-8000-000000000002', code: 'NRL-PEER-26', name: 'Neurolyn Peer Exchange', status: 'ACTIVE', startDate: '2026-02-01', endDate: '2026-12-31' },
  ],
  topics: [
    { id: 't1', code: 'HF_MGMT', label: 'Heart Failure Management', active: true },
    { id: 't2', code: 'LIPID', label: 'Lipid Control', active: true },
    { id: 't3', code: 'MIGRAINE', label: 'Migraine Prophylaxis', active: true },
  ],
  regions: [
    { id: 'r1', code: 'EMEA_W', label: 'EMEA West', active: true },
    { id: 'r2', code: 'EMEA_N', label: 'EMEA North', active: true },
    { id: 'r3', code: 'NA_E', label: 'North America East', active: true },
  ],
  formats: [EventFormat.IN_PERSON, EventFormat.VIRTUAL, EventFormat.HYBRID, EventFormat.ROUNDTABLE, EventFormat.ON_DEMAND],
  periodMin: '2024-07',
  periodMax: '2026-06',
};

export const notifications: Paginated<NotificationItem> = {
  items: [
    {
      notificationId: 'n1000000-0000-4000-8000-000000000001',
      kind: 'REVIEW',
      severity: 'INFO',
      title: 'Two results awaiting compliance sign-off',
      body: 'Cardivex Speaker Series H1 — submitted by A. Okafor.',
      href: '/reviews',
      createdAt: new Date(Date.now() - 40 * 60_000).toISOString(),
      readAt: null,
    },
    {
      notificationId: 'n1000000-0000-4000-8000-000000000002',
      kind: 'UPLOAD',
      severity: 'WARNING',
      title: 'Attendance batch partially accepted',
      body: '312 rows quarantined pending identity resolution.',
      href: '/data-health',
      createdAt: new Date(Date.now() - 3 * 3600_000).toISOString(),
      readAt: null,
    },
    {
      notificationId: 'n1000000-0000-4000-8000-000000000003',
      kind: 'RUN',
      severity: 'SUCCESS',
      title: 'Causal estimation run completed',
      body: 'dv_2026_07_28 · 41 events estimated.',
      href: '/data-health',
      createdAt: new Date(Date.now() - 26 * 3600_000).toISOString(),
      readAt: new Date(Date.now() - 20 * 3600_000).toISOString(),
    },
  ],
  nextCursor: null,
  totalCount: 3,
};

export const searchCorpus: SearchResult[] = [
  { id: 'e1', kind: 'EVENT', title: 'Heart Failure Management — Lisbon', subtitle: 'Cardivex · 12 Mar 2026 · In person', href: '/events' },
  { id: 'e2', kind: 'EVENT', title: 'Lipid Control Roundtable — Dublin', subtitle: 'Cardivex · 04 Apr 2026 · Roundtable', href: '/events' },
  { id: 'c1', kind: 'CAMPAIGN', title: 'Cardivex Speaker Series H1', subtitle: 'Active · 24 events', href: '/events' },
  { id: 'b1', kind: 'BRAND', title: 'Cardivex', subtitle: 'Cardiology', href: '/portfolio' },
  { id: 'u1', kind: 'UPLOAD', title: 'attendance_2026_06.csv', subtitle: 'Partially accepted · 3 days ago', href: '/data-health' },
];

export const savedViews: SavedView[] = [
  {
    savedViewId: 's1000000-0000-4000-8000-000000000001',
    name: 'Strong evidence, EMEA West',
    scope: 'portfolio',
    query: 'region=EMEA_W&evidenceGrade=STRONG',
    isShared: true,
    createdAt: new Date(Date.now() - 12 * 86400_000).toISOString(),
  },
  {
    savedViewId: 's1000000-0000-4000-8000-000000000002',
    name: 'Cardivex — current quarter',
    scope: 'portfolio',
    query: 'brand=CDX&periodFrom=2026-04&periodTo=2026-06',
    isShared: false,
    createdAt: new Date(Date.now() - 4 * 86400_000).toISOString(),
  },
];

export const uploadTemplates: UploadTemplate[] = [
  {
    datasetType: DatasetType.ATTENDANCE,
    templateVersion: 'v3',
    label: 'Registrations & attendance',
    description: 'One row per HCP per event, with the verification source that proves attendance.',
    acceptedFormats: [FileFormat.CSV, FileFormat.XLSX],
    downloadUrl: '/api/v1/uploads/templates/ATTENDANCE/v3',
    dataDictionaryUrl: null,
    maxBytes: 26_214_400,
    maxRows: 200_000,
  },
  {
    datasetType: DatasetType.EVENT_COST,
    templateVersion: 'v2',
    label: 'Event costs',
    description: 'Fully loaded cost lines per event, by cost category.',
    acceptedFormats: [FileFormat.CSV, FileFormat.XLSX],
    downloadUrl: '/api/v1/uploads/templates/EVENT_COST/v2',
    dataDictionaryUrl: null,
    maxBytes: 26_214_400,
    maxRows: 200_000,
  },
];

export const uploadHistory: Paginated<UploadBatch> = {
  items: [
    {
      uploadId: 'u1000000-0000-4000-8000-000000000001',
      datasetType: DatasetType.ATTENDANCE,
      fileName: 'attendance_2026_06.csv',
      fileFormat: FileFormat.CSV,
      status: UploadStatus.PARTIALLY_ACCEPTED,
      uploadProgress: 1,
      processingProgress: 1,
      rowsTotal: 4820,
      rowsAccepted: 4508,
      rowsRejected: 0,
      rowsQuarantined: 312,
      issues: [
        {
          severity: 'QUARANTINE',
          code: 'HCP_IDENTITY_UNRESOLVED',
          message: 'Source HCP identifier did not resolve to a master record.',
          rowNumber: 118,
          column: 'source_hcp_id',
          occurrences: 312,
        },
      ],
      errorReportUrl: '/api/v1/uploads/u1000000-0000-4000-8000-000000000001/errors',
      receipt: {
        bucket: 'northwind-raw',
        objectKey: 'attendance/2026/06/attendance_2026_06.csv',
        checksumSha256: '3b1f9c7e2a5d4408b6c1e0f7a9d2b8c4e5f60718293a4b5c6d7e8f9012345678',
        sizeBytes: 1_204_338,
        storedAt: new Date(Date.now() - 3 * 86400_000).toISOString(),
      },
      submittedByName: 'M. Halvorsen',
      createdAt: new Date(Date.now() - 3 * 86400_000).toISOString(),
      completedAt: new Date(Date.now() - 3 * 86400_000 + 420_000).toISOString(),
      correctsUploadId: null,
    },
  ],
  nextCursor: null,
  totalCount: 1,
};

/**
 * A KPI row shaped exactly like the real payload, so shell components can be
 * exercised. The dashboard agent replaces the *source*, not the shape.
 */
export function buildKpis(): Kpi[] {
  const rng = lcg(20260728);
  const spec: ReadonlyArray<[string, string, Kpi['unit'], number, boolean]> = [
    ['fully_loaded_spend', 'Fully loaded spend', 'CURRENCY', 4_182_000, false],
    ['verified_reach', 'Verified reach', 'COUNT', 12_486, true],
    ['estimable_share', 'Events with estimable evidence', 'PERCENT', 0.79, true],
    ['incremental_nrx', 'Incremental NRx', 'RX', 18_940, true],
    ['net_roi', 'Net ROI', 'MULTIPLE', 2.34, true],
  ];
  return spec.map(([key, label, unit, value, higherIsBetter]) => ({
    key,
    label,
    unit,
    value,
    interval:
      unit === 'RX' || unit === 'MULTIPLE'
        ? { point: value, lower: value * 0.82, upper: value * 1.19, confidenceLevel: 0.95 }
        : null,
    comparisonValue: value * (0.88 + rng() * 0.2),
    comparisonLabel: 'vs. previous 6 months',
    changeRatio: rng() * 0.24 - 0.08,
    higherIsBetter,
    evidence:
      unit === 'RX' || unit === 'MULTIPLE'
        ? {
            status: EvidenceStatus.ESTIMATED,
            grade: EvidenceGrade.MODERATE,
            controlStrategy: ControlStrategy.INVITED_NON_ATTENDEE,
            controlStrategyJustification: null,
            estimator: EstimatorKind.COHORT_TIME_ATT,
            failedGates: [],
            reason: null,
          }
        : null,
    definition: null,
    lineage: {
      tenantId: TENANT_ID,
      dataVersion: 'dv_2026_07_28',
      runId: 'run_8f31c0',
      modelVersion: 'm3_v4',
      financeVersion: 'fin_2026_q2',
      publicationState: PublicationState.PUBLISHED,
      computedAt: new Date(Date.now() - 5 * 3600_000).toISOString(),
    },
  }));
}
