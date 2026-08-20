'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';

import type { Role } from '@/lib/api/enums';
import type { Session } from '@/lib/api/types';
import { env } from '@/lib/env';
import { useFilterOptions, useFreshness } from '@/lib/api/queries/shell';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { VisuallyHidden } from '@/components/ui/visually-hidden';
import { CommandPalette, useCommandPalette } from './CommandPalette';
import { SideNav } from './SideNav';
import { SyntheticBanner } from './SyntheticBanner';
import { TopBar } from './TopBar';

/**
 * The authenticated frame.
 *
 * Layout is a fixed-height flex column with exactly one scroll container (the
 * `<main>`): a page whose header scrolls away with the table it labels is
 * unusable at the density this product runs at, and nesting scrollers is how you
 * get a table whose sticky header sticks to the wrong thing.
 *
 * Landmarks: one `<header>` (banner) from `TopBar`, one `<nav>` (navigation)
 * from `SideNav`, one `<main>`. The skip link is the first tab stop and jumps
 * straight past the rail — without it, a keyboard user pays ~20 tab presses to
 * reach the content on every navigation.
 */

const COLLAPSE_KEY = 'sr.nav.collapsed';
const BRAND_SCOPE_KEY = 'sr.brandScope';

export interface AppShellProps {
  session: Session;
  children: React.ReactNode;
}

export function AppShell({ session, children }: AppShellProps) {
  const router = useRouter();
  const roles = session.roles as readonly Role[];
  const tenantId = session.activeTenant?.tenantId ?? null;

  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const [brandScope, setBrandScope] = React.useState<readonly string[]>([]);
  const palette = useCommandPalette();

  // Read persisted UI state after mount. Doing it in `useState`'s initialiser
  // would diverge from the server render and produce a hydration mismatch; the
  // one-frame flash of an expanded rail is the cheaper trade.
  React.useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === '1');
      const stored = window.localStorage.getItem(`${BRAND_SCOPE_KEY}.${tenantId ?? 'none'}`);
      if (stored) setBrandScope(JSON.parse(stored) as string[]);
    } catch {
      // Private browsing, or storage disabled by policy. Defaults are fine.
    }
  }, [tenantId]);

  const onCollapsedChange = React.useCallback((next: boolean) => {
    setCollapsed(next);
    try {
      window.localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0');
    } catch {
      /* non-fatal */
    }
  }, []);

  const onBrandScopeChange = React.useCallback(
    (next: string[]) => {
      setBrandScope(next);
      try {
        window.localStorage.setItem(`${BRAND_SCOPE_KEY}.${tenantId ?? 'none'}`, JSON.stringify(next));
      } catch {
        /* non-fatal */
      }
    },
    [tenantId],
  );

  const freshness = useFreshness(tenantId);
  const filterOptions = useFilterOptions(tenantId);

  /**
   * Tenant switching is a full document navigation on purpose. Every query key
   * in the tree is tenant-scoped, and swapping the id in place would leave the
   * previous tenant's cached rows on screen until each refetch resolves — one
   * customer's numbers under another customer's name, however briefly.
   */
  const onSwitchTenant = React.useCallback((nextTenantId: string) => {
    window.location.assign(`/api/v1/auth/switch-tenant?tenantId=${encodeURIComponent(nextTenantId)}`);
  }, []);

  // Close the mobile drawer whenever a navigation completes.
  const closeMobileNav = React.useCallback(() => setMobileNavOpen(false), []);

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-canvas">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>

      {session.activeTenant?.syntheticMode ? (
        <SyntheticBanner environmentLabel={env.environmentLabel} />
      ) : null}

      <div className="flex min-h-0 flex-1">
        <div className="hidden shrink-0 lg:block">
          <SideNav roles={roles} collapsed={collapsed} onCollapsedChange={onCollapsedChange} />
        </div>

        <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
          <SheetContent side="left" size="sm" className="w-60 border-none bg-nav-bg p-0 sm:max-w-60">
            <VisuallyHidden>
              <SheetTitle>Navigation</SheetTitle>
            </VisuallyHidden>
            <SideNav
              roles={roles}
              collapsed={false}
              onCollapsedChange={onCollapsedChange}
              inSheet
              onNavigate={closeMobileNav}
            />
          </SheetContent>
        </Sheet>

        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar
            session={session}
            freshness={freshness.data}
            freshnessLoading={freshness.isPending}
            periodMin={filterOptions.data?.periodMin}
            periodMax={filterOptions.data?.periodMax}
            onOpenCommandPalette={() => palette.setOpen(true)}
            onOpenMobileNav={() => setMobileNavOpen(true)}
            onSwitchTenant={onSwitchTenant}
            brandScope={brandScope}
            onBrandScopeChange={onBrandScopeChange}
          />

          {/* The single scroll container. `tabIndex={-1}` makes the skip link's
              target focusable so focus actually moves, not just the viewport. */}
          <main
            id="main-content"
            tabIndex={-1}
            className="scroll-thin min-h-0 flex-1 overflow-y-auto outline-none"
          >
            {children}
          </main>
        </div>
      </div>

      <CommandPalette open={palette.open} onOpenChange={palette.setOpen} roles={roles} />
    </div>
  );
}
