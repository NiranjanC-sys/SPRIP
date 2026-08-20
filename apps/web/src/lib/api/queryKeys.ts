/**
 * Query-key factory. Every key in the app is produced here.
 *
 * Two properties matter and both are easy to lose if keys are written inline:
 *
 *  1. **Tenant scoping.** Analytical keys carry `tenantId`. Switching tenant in
 *     the top bar must not serve a cached Portfolio from the previous tenant —
 *     that is a cross-tenant leak in the browser, and no server control can fix
 *     it after the fact.
 *  2. **Prefix invalidation.** Keys are hierarchical arrays, so
 *     `invalidateQueries({ queryKey: qk.portfolio.all(tenantId) })` clears every
 *     variant after a publish without enumerating filter permutations.
 *
 * `filters` objects are serialised by TanStack Query's structural hashing, which
 * is key-order independent, so callers may pass filter objects directly.
 */

export type FilterKey = Readonly<Record<string, unknown>>;

export const queryKeys = {
  /** Not tenant-scoped: it is what *tells* us the tenant. */
  session: () => ['session'] as const,

  tenant: {
    current: () => ['tenant', 'current'] as const,
    filterOptions: (tenantId: string) => ['tenant', tenantId, 'filter-options'] as const,
    freshness: (tenantId: string) => ['tenant', tenantId, 'freshness'] as const,
  },

  notifications: {
    all: () => ['notifications'] as const,
    list: (unreadOnly: boolean) => ['notifications', { unreadOnly }] as const,
  },

  search: (term: string) => ['search', term] as const,

  savedViews: {
    all: (tenantId: string) => ['saved-views', tenantId] as const,
    byScope: (tenantId: string, scope: string) => ['saved-views', tenantId, scope] as const,
  },

  reference: {
    brands: (tenantId: string) => ['reference', tenantId, 'brands'] as const,
    campaigns: (tenantId: string, brandId?: string) =>
      ['reference', tenantId, 'campaigns', { brandId: brandId ?? null }] as const,
    taxonomy: (tenantId: string, kind: string) =>
      ['reference', tenantId, 'taxonomy', kind] as const,
  },

  uploads: {
    all: (tenantId: string) => ['uploads', tenantId] as const,
    list: (tenantId: string, filters: FilterKey) => ['uploads', tenantId, 'list', filters] as const,
    detail: (tenantId: string, uploadId: string) => ['uploads', tenantId, uploadId] as const,
    templates: (tenantId: string) => ['uploads', tenantId, 'templates'] as const,
  },

  /* --- analytical surfaces owned by the dashboard agent ----------------- */

  portfolio: {
    all: (tenantId: string) => ['portfolio', tenantId] as const,
    summary: (tenantId: string, filters: FilterKey) =>
      ['portfolio', tenantId, 'summary', filters] as const,
    breakdown: (tenantId: string, dimension: string, filters: FilterKey) =>
      ['portfolio', tenantId, 'breakdown', dimension, filters] as const,
  },

  events: {
    all: (tenantId: string) => ['events', tenantId] as const,
    explorer: (tenantId: string, filters: FilterKey) =>
      ['events', tenantId, 'explorer', filters] as const,
    evidence: (tenantId: string, eventId: string) =>
      ['events', tenantId, eventId, 'evidence'] as const,
  },

  finance: {
    all: (tenantId: string) => ['finance', tenantId] as const,
    assumptions: (tenantId: string, filters: FilterKey) =>
      ['finance', tenantId, 'assumptions', filters] as const,
    roiResults: (tenantId: string, filters: FilterKey) =>
      ['finance', tenantId, 'roi-results', filters] as const,
  },

  reviews: {
    all: (tenantId: string) => ['reviews', tenantId] as const,
    queue: (tenantId: string, filters: FilterKey) =>
      ['reviews', tenantId, 'queue', filters] as const,
  },

  simulations: {
    all: (tenantId: string) => ['simulations', tenantId] as const,
    detail: (tenantId: string, simulationId: string) =>
      ['simulations', tenantId, simulationId] as const,
  },

  budget: {
    all: (tenantId: string) => ['budget', tenantId] as const,
    scenario: (tenantId: string, scenarioId: string) => ['budget', tenantId, scenarioId] as const,
  },

  ai: {
    all: (tenantId: string) => ['ai', tenantId] as const,
    interaction: (tenantId: string, interactionId: string) =>
      ['ai', tenantId, interactionId] as const,
  },

  dataHealth: {
    all: (tenantId: string) => ['data-health', tenantId] as const,
    summary: (tenantId: string, filters: FilterKey) =>
      ['data-health', tenantId, 'summary', filters] as const,
    runs: (tenantId: string, filters: FilterKey) => ['data-health', tenantId, 'runs', filters] as const,
    models: (tenantId: string) => ['data-health', tenantId, 'models'] as const,
    identityIssues: (tenantId: string, filters: FilterKey) =>
      ['data-health', tenantId, 'identity-issues', filters] as const,
  },

  platform: {
    tenants: (filters: FilterKey) => ['platform', 'tenants', filters] as const,
    tenant: (tenantId: string) => ['platform', 'tenants', tenantId] as const,
    health: () => ['platform', 'health'] as const,
  },

  admin: {
    company: (tenantId: string) => ['admin', tenantId, 'company'] as const,
    memberships: (tenantId: string, filters: FilterKey) =>
      ['admin', tenantId, 'memberships', filters] as const,
    invitations: (tenantId: string) => ['admin', tenantId, 'invitations'] as const,
    vendors: (tenantId: string, filters: FilterKey) =>
      ['admin', tenantId, 'vendors', filters] as const,
  },

  vendor: {
    uploads: (tenantId: string, filters: FilterKey) =>
      ['vendor', tenantId, 'uploads', filters] as const,
    assignments: (tenantId: string) => ['vendor', tenantId, 'assignments'] as const,
  },
} as const;

/** Short alias — `qk.portfolio.summary(...)` reads better at the call site. */
export const qk = queryKeys;

/**
 * Everything that becomes stale when a new data version is published. The
 * publish mutation invalidates exactly these roots rather than nuking the whole
 * cache, so the shell (session, notifications, filter options) survives.
 */
export function analyticalRoots(tenantId: string): readonly unknown[][] {
  return [
    [...qk.portfolio.all(tenantId)],
    [...qk.events.all(tenantId)],
    [...qk.finance.all(tenantId)],
    [...qk.reviews.all(tenantId)],
    [...qk.simulations.all(tenantId)],
    [...qk.budget.all(tenantId)],
    [...qk.ai.all(tenantId)],
    [...qk.dataHealth.all(tenantId)],
  ];
}
