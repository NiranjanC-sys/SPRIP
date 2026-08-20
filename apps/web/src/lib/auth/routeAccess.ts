import { Role, landingRouteForRoles } from '@/lib/api/enums';

/**
 * The route → role map.
 *
 * Single source of truth for three consumers: `middleware.ts` (edge gate), the
 * server layouts (per-route check, the authoritative one on the Next side), and
 * `navigation.ts` (what to render).
 *
 * plan.md §5.3 is explicit that a hidden nav item is not an authorization
 * control. So the navigation config *derives* from this table rather than
 * declaring its own visibility — that way a nav entry can never be visible for a
 * route the gate would refuse, and adding a route without deciding its roles is
 * a compile error rather than an open door.
 *
 * The FastAPI layer enforces the same rules independently. Both must agree; this
 * side exists to avoid rendering a page the API will only 403.
 */

export interface RouteRule {
  /** Matches this exact path or any path beneath it. */
  prefix: string;
  /** Union semantics: holding any one of these roles grants access. */
  roles: readonly Role[];
}

const ANALYST_ROLES = [
  Role.ANALYTICS_LEAD,
  Role.BRAND_MANAGER,
  Role.EXECUTIVE_VIEWER,
  Role.PHARMA_ADMIN,
] as const;

/**
 * Ordered most-specific-first. `findRouteRule` returns the first match, so a
 * nested exception (e.g. `/data/uploads` for vendors) must precede its parent.
 */
export const ROUTE_RULES: readonly RouteRule[] = [
  // --- platform console: deliberately no access to tenant business data ---
  { prefix: '/platform', roles: [Role.PLATFORM_ADMIN] },

  // --- tenant administration ---
  { prefix: '/admin', roles: [Role.PHARMA_ADMIN] },

  // --- vendor portal: own submissions only ---
  { prefix: '/vendor', roles: [Role.VENDOR_CONTRIBUTOR] },

  // --- data management workspace ---
  {
    prefix: '/data',
    roles: [Role.DATA_STEWARD, Role.PHARMA_ADMIN, Role.ANALYTICS_LEAD],
  },
  {
    prefix: '/data-health',
    roles: [Role.DATA_STEWARD, Role.ANALYTICS_LEAD, Role.PHARMA_ADMIN, Role.COMPLIANCE_REVIEWER],
  },

  // --- analytical modules ---
  { prefix: '/portfolio', roles: [...ANALYST_ROLES, Role.FINANCE_REVIEWER, Role.COMPLIANCE_REVIEWER] },
  { prefix: '/events', roles: [...ANALYST_ROLES, Role.FINANCE_REVIEWER, Role.COMPLIANCE_REVIEWER] },
  { prefix: '/finance', roles: [Role.FINANCE_REVIEWER, Role.ANALYTICS_LEAD, Role.PHARMA_ADMIN] },
  {
    prefix: '/reviews',
    roles: [Role.COMPLIANCE_REVIEWER, Role.ANALYTICS_LEAD, Role.FINANCE_REVIEWER],
  },
  // Simulator and planner write scenarios, so the read-only executive role is
  // excluded — plan.md §5.2 scopes Executive Viewer to published results.
  { prefix: '/simulator', roles: [Role.ANALYTICS_LEAD, Role.BRAND_MANAGER] },
  { prefix: '/budget', roles: [Role.ANALYTICS_LEAD, Role.BRAND_MANAGER, Role.FINANCE_REVIEWER] },
  { prefix: '/ai', roles: [...ANALYST_ROLES, Role.FINANCE_REVIEWER, Role.COMPLIANCE_REVIEWER] },

  // --- account pages every authenticated user reaches ---
  { prefix: '/settings', roles: [...Object.values(Role)] },
  { prefix: '/no-access', roles: [...Object.values(Role)] },
];

/** Paths reachable without a session. Everything else requires one. */
export const PUBLIC_PREFIXES: readonly string[] = [
  '/login',
  '/accept-invitation',
  '/session-expired',
  '/logout',
];

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function findRouteRule(pathname: string): RouteRule | undefined {
  return ROUTE_RULES.find((r) => pathname === r.prefix || pathname.startsWith(`${r.prefix}/`));
}

/**
 * `undefined` rule means the path is not gated by role (e.g. `/forbidden`,
 * `/`), which is a deliberate allow rather than an oversight — every gated
 * prefix is listed above and the middleware still requires a session.
 */
export function canAccessPath(pathname: string, roles: readonly Role[]): boolean {
  const rule = findRouteRule(pathname);
  if (!rule) return true;
  return rule.roles.some((r) => roles.includes(r));
}

export { landingRouteForRoles };
