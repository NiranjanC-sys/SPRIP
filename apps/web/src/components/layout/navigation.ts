import type { LucideIcon } from 'lucide-react';
import {
  Activity,
  Boxes,
  Building2,
  CalendarDays,
  Fingerprint,
  GitBranch,
  Landmark,
  LayoutDashboard,
  MessagesSquare,
  ScrollText,
  ServerCog,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Tags,
  Target,
  Truck,
  UploadCloud,
  Users,
} from 'lucide-react';

import type { Role } from '@/lib/api/enums';
import { findRouteRule } from '@/lib/auth/routeAccess';

/**
 * The navigation tree.
 *
 * Two rules this file exists to enforce:
 *
 *  1. **Every item declares what gates it.** There is no "just render it and see
 *     what happens" entry. `effectiveRoles()` resolves an item's audience from
 *     `ROUTE_RULES` — the same table the middleware and the server layouts read
 *     — so a nav link can never be visible for a route the gate would refuse.
 *     An item may *narrow* that set (`roles`), never widen it: the resolver
 *     intersects, so a typo produces an invisible link rather than an open door.
 *
 *  2. **Hiding is a courtesy, not a control.** plan.md §5.3. Filtering this tree
 *     stops us from showing people doors they cannot open; it is `middleware.ts`
 *     plus the per-route server check that actually stops them walking through.
 *
 * Adding a route therefore means adding it to `ROUTE_RULES` first. If it is not
 * there, `effectiveRoles()` returns an empty set and the item never renders —
 * which is the correct failure direction.
 */

export interface NavItem {
  /** Stable key for React and for the command palette index. */
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
  /**
   * Optional narrowing of the route's audience. Must be a subset of the route
   * rule's roles; anything outside it is discarded by `effectiveRoles`.
   */
  roles?: readonly Role[];
  /** Short line shown in the command palette and the collapsed-rail tooltip. */
  description?: string;
  /** Matches child paths too. Off for items whose siblings live beneath them. */
  matchNested?: boolean;
}

export interface NavGroup {
  id: string;
  /** Rendered as a section heading; omitted for the primary group. */
  label?: string;
  items: readonly NavItem[];
}

/**
 * Resolves who may see an item: the route rule's roles, intersected with any
 * explicit narrowing. Unknown route → nobody.
 */
export function effectiveRoles(item: NavItem): readonly Role[] {
  const rule = findRouteRule(item.href);
  if (!rule) return [];
  if (!item.roles) return rule.roles;
  return rule.roles.filter((role) => item.roles?.includes(role));
}

export function canSee(item: NavItem, roles: readonly Role[]): boolean {
  return effectiveRoles(item).some((role) => roles.includes(role));
}

/* ===========================================================================
 * The tree
 * ======================================================================== */

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    id: 'analyze',
    label: 'Analyze',
    items: [
      {
        id: 'portfolio',
        label: 'Portfolio',
        href: '/portfolio',
        icon: LayoutDashboard,
        description: 'Programme-level reach, lift and ROI across brands',
        matchNested: true,
      },
      {
        id: 'events',
        label: 'Events',
        href: '/events',
        icon: CalendarDays,
        description: 'Every speaker programme, its cohort and its evidence grade',
        matchNested: true,
      },
      {
        id: 'finance',
        label: 'Finance & ROI',
        href: '/finance',
        icon: Landmark,
        description: 'Fully loaded spend, benefit-cost ratio and net ROI',
        matchNested: true,
      },
      {
        id: 'reviews',
        label: 'Review queue',
        href: '/reviews',
        icon: ShieldCheck,
        description: 'Results awaiting compliance and finance sign-off',
        matchNested: true,
      },
    ],
  },
  {
    id: 'plan',
    label: 'Plan',
    items: [
      {
        id: 'simulator',
        label: 'Scenario simulator',
        href: '/simulator',
        icon: SlidersHorizontal,
        description: 'Forecast a programme mix before committing budget',
        matchNested: true,
      },
      {
        id: 'budget',
        label: 'Budget optimiser',
        href: '/budget',
        icon: Target,
        description: 'Allocate spend under constraints, with evidence caps applied',
        matchNested: true,
      },
      {
        id: 'ai',
        label: 'Ask the data',
        href: '/ai',
        icon: MessagesSquare,
        description: 'Grounded answers with citations, or an explicit refusal',
        matchNested: true,
      },
    ],
  },
  {
    id: 'data',
    label: 'Data',
    items: [
      {
        id: 'data-health',
        label: 'Data & model health',
        href: '/data-health',
        icon: Activity,
        description: 'Freshness, coverage, run status and drift',
        matchNested: true,
      },
      {
        id: 'data-uploads',
        label: 'Uploads',
        href: '/data/uploads',
        icon: UploadCloud,
        description: 'Submit and track ingestion batches',
        matchNested: true,
      },
      {
        id: 'data-identity',
        label: 'Identity resolution',
        href: '/data/identity',
        icon: Fingerprint,
        description: 'Review and adjudicate HCP matches',
        matchNested: true,
      },
      {
        id: 'data-taxonomy',
        label: 'Reference data',
        href: '/data/taxonomy',
        icon: Tags,
        description: 'Brands, campaigns, topics, regions and formats',
        matchNested: true,
      },
      {
        id: 'data-versions',
        label: 'Data versions',
        href: '/data/versions',
        icon: GitBranch,
        description: 'Immutable snapshots every published number resolves to',
        matchNested: true,
      },
    ],
  },
  {
    id: 'vendor',
    label: 'Submissions',
    items: [
      {
        id: 'vendor-uploads',
        label: 'My submissions',
        href: '/vendor/uploads',
        icon: UploadCloud,
        description: 'Files your organisation has sent, and their validation results',
        matchNested: true,
      },
      {
        id: 'vendor-templates',
        label: 'Templates',
        href: '/vendor/templates',
        icon: Boxes,
        description: 'Current file specifications and data dictionaries',
        matchNested: true,
      },
    ],
  },
  {
    id: 'admin',
    label: 'Administration',
    items: [
      {
        id: 'admin-company',
        label: 'Company',
        href: '/admin/company',
        icon: Building2,
        description: 'Tenant profile, reporting currency and feature flags',
        matchNested: true,
      },
      {
        id: 'admin-users',
        label: 'Users & roles',
        href: '/admin/users',
        icon: Users,
        description: 'Invitations, role assignment and brand scoping',
        matchNested: true,
      },
      {
        id: 'admin-vendors',
        label: 'Vendors',
        href: '/admin/vendors',
        icon: Truck,
        description: 'Contributing agencies and what each may submit',
        matchNested: true,
      },
      {
        id: 'admin-audit',
        label: 'Audit log',
        href: '/admin/audit',
        icon: ScrollText,
        description: 'Who did what, to which record, when',
        matchNested: true,
      },
    ],
  },
  {
    id: 'platform',
    label: 'Platform',
    items: [
      {
        id: 'platform-companies',
        label: 'Companies',
        href: '/platform/companies',
        icon: Building2,
        description: 'Tenant provisioning, status and data region',
        matchNested: true,
      },
      {
        id: 'platform-operations',
        label: 'Operations',
        href: '/platform/operations',
        icon: ServerCog,
        description: 'Job queues, worker health and release state',
        matchNested: true,
      },
      {
        id: 'platform-audit',
        label: 'Platform audit',
        href: '/platform/audit',
        icon: ScrollText,
        description: 'Cross-tenant administrative actions',
        matchNested: true,
      },
    ],
  },
];

/** Rendered separately, pinned to the bottom of the rail. */
export const NAV_FOOTER: readonly NavItem[] = [
  {
    id: 'settings',
    label: 'Settings',
    href: '/settings',
    icon: Settings,
    description: 'Profile, notifications and appearance',
    matchNested: true,
  },
];

/**
 * Filters the tree for a principal. Groups that end up empty disappear entirely
 * rather than leaving a bare heading — an "Administration" label above nothing
 * tells a user something exists that they cannot have, which is the same
 * information leak the `/forbidden` copy is careful to avoid.
 */
export function visibleNavigation(roles: readonly Role[]): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => canSee(item, roles)),
  })).filter((group) => group.items.length > 0);
}

export function visibleFooterNavigation(roles: readonly Role[]): NavItem[] {
  return NAV_FOOTER.filter((item) => canSee(item, roles));
}

/** Flat list, used by the command palette and the breadcrumb resolver. */
export function flatNavigation(roles: readonly Role[]): NavItem[] {
  return [...visibleNavigation(roles).flatMap((g) => g.items), ...visibleFooterNavigation(roles)];
}

/**
 * Active-state test. `matchNested` is the difference between `/data/uploads`
 * staying lit while you are on `/data/uploads/abc123` and it going dark the
 * moment you open a detail page.
 */
export function isNavItemActive(item: NavItem, pathname: string): boolean {
  if (pathname === item.href) return true;
  return Boolean(item.matchNested) && pathname.startsWith(`${item.href}/`);
}

/** Best-effort label for a path segment, so breadcrumbs read in product terms. */
export function navLabelForPath(pathname: string): string | undefined {
  const all = [...NAV_GROUPS.flatMap((g) => g.items), ...NAV_FOOTER];
  const match = all
    .filter((item) => isNavItemActive(item, pathname))
    .sort((a, b) => b.href.length - a.href.length)[0];
  return match?.label;
}
