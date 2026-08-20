'use client';

import { Menu, Search } from 'lucide-react';

import type { Freshness, Session } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { IconButton } from '@/components/ui/icon-button';
import { Kbd } from '@/components/ui/kbd';
import { FreshnessIndicator } from './FreshnessIndicator';
import { NotificationCenter } from './NotificationCenter';
import { PeriodFilter } from './PeriodFilter';
import { TenantSwitcher } from './TenantSwitcher';
import { ThemeToggle } from './ThemeToggle';
import { UserMenu } from './UserMenu';

/**
 * The top bar: who / when / how fresh, then the account controls.
 *
 * Reading order is the order an analyst actually needs: *whose* data (tenant and
 * brand scope), *which* period, then *how stale*. The account cluster is pushed
 * to the far right because it is the least frequently used thing here.
 *
 * It is `<header>` with the search affordance inside it rather than a `<nav>`,
 * so the page has exactly one banner landmark and the rail keeps the only
 * navigation landmark.
 */

export interface TopBarProps {
  session: Session;
  freshness: Freshness | undefined;
  freshnessLoading?: boolean;
  periodMin?: string | null;
  periodMax?: string | null;
  onOpenCommandPalette: () => void;
  onOpenMobileNav: () => void;
  onSwitchTenant?: (tenantId: string) => void;
  brandScope?: readonly string[];
  onBrandScopeChange?: (brandIds: string[]) => void;
  className?: string;
}

export function TopBar({
  session,
  freshness,
  freshnessLoading,
  periodMin,
  periodMax,
  onOpenCommandPalette,
  onOpenMobileNav,
  onSwitchTenant,
  brandScope,
  onBrandScopeChange,
  className,
}: TopBarProps) {
  return (
    <header
      className={cn(
        'flex h-14 shrink-0 items-center gap-2 border-b border-border bg-surface px-3',
        className,
      )}
    >
      <IconButton
        label="Open navigation"
        variant="ghost"
        size="sm"
        onClick={onOpenMobileNav}
        className="lg:hidden"
      >
        <Menu />
      </IconButton>

      <TenantSwitcher
        session={session}
        onSwitchTenant={onSwitchTenant}
        brandScope={brandScope}
        onBrandScopeChange={onBrandScopeChange}
      />

      {/* Search is a button, not an input: the palette owns the real field, and
          two focusable text boxes for one search is a worse keyboard model. */}
      <button
        type="button"
        onClick={onOpenCommandPalette}
        className="ml-auto flex h-8 items-center gap-2 rounded-md border border-border bg-surface-sunken px-2.5 text-xs text-text-subtle hover:border-border-strong md:ml-4 md:w-64 lg:w-80"
      >
        <Search aria-hidden="true" className="size-3.5 shrink-0" />
        <span className="hidden truncate md:inline">Search or jump to…</span>
        <Kbd className="ml-auto hidden md:inline-flex">⌘K</Kbd>
      </button>

      <div className="ml-auto flex items-center gap-1.5 md:ml-0">
        {session.activeTenant ? (
          <>
            <PeriodFilter min={periodMin} max={periodMax} className="hidden sm:inline-flex" />
            <FreshnessIndicator
              freshness={freshness}
              loading={freshnessLoading}
              className="hidden md:flex"
            />
          </>
        ) : null}
        <NotificationCenter />
        <ThemeToggle />
        <UserMenu session={session} />
      </div>
    </header>
  );
}
