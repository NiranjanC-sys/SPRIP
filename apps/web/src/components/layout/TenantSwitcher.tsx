'use client';

import * as React from 'react';
import { Building2, Check, ChevronsUpDown, Layers } from 'lucide-react';

import type { Session } from '@/lib/api/types';
import { MembershipStatus } from '@/lib/api/enums';
import { cn, humanizeEnum } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

/**
 * Tenant and brand scope.
 *
 * Kept as one control because they are one question — "whose data am I looking
 * at" — and because splitting them invites the state where a brand from tenant A
 * is still selected after switching to tenant B.
 *
 * Switching tenants is a full navigation, not a client state change: every
 * cached query in the tree is scoped to a tenant id, and quietly swapping the id
 * underneath a populated cache is how one customer's numbers end up rendered
 * under another customer's name for the few hundred milliseconds before the
 * refetch lands. A hard navigation costs a reload and removes the entire class
 * of bug.
 */

export interface TenantSwitcherProps {
  session: Session;
  /** Called with the target tenant id. The shell performs a hard navigation. */
  onSwitchTenant?: (tenantId: string) => void;
  /** Current brand scope filter (brand ids). Empty means "all my brands". */
  brandScope?: readonly string[];
  onBrandScopeChange?: (brandIds: string[]) => void;
  className?: string;
}

export function TenantSwitcher({
  session,
  onSwitchTenant,
  brandScope = [],
  onBrandScopeChange,
  className,
}: TenantSwitcherProps) {
  const active = session.activeTenant;
  const memberships = session.memberships;
  const brands = session.brandScopes;

  const switchable = memberships.filter((m) => m.status === MembershipStatus.ACTIVE);
  const canSwitchTenant = switchable.length > 1 && Boolean(onSwitchTenant);
  const canScopeBrands = brands.length > 1 && Boolean(onBrandScopeChange);

  const scopeLabel = React.useMemo(() => {
    if (brandScope.length === 0) return brands.length > 1 ? 'All brands' : (brands[0]?.brandName ?? null);
    if (brandScope.length === 1) {
      return brands.find((b) => b.brandId === brandScope[0])?.brandName ?? '1 brand';
    }
    return `${brandScope.length} brands`;
  }, [brandScope, brands]);

  // Platform admins hold no tenant membership by design — the console they land
  // on is deliberately outside tenant data.
  if (!active) {
    return (
      <div className={cn('flex items-center gap-2 px-2 text-sm', className)}>
        <Building2 aria-hidden="true" className="size-4 text-text-subtle" />
        <span className="font-medium text-text">Platform console</span>
      </div>
    );
  }

  const inert = !canSwitchTenant && !canScopeBrands;

  const trigger = (
    <span className="flex min-w-0 flex-col items-start leading-tight">
      <span className="flex items-center gap-1.5">
        <span className="truncate text-sm font-semibold text-text">{active.name}</span>
        {active.status !== 'ACTIVE' ? (
          <Badge variant="warning" size="sm">
            {humanizeEnum(active.status)}
          </Badge>
        ) : null}
      </span>
      {scopeLabel ? (
        <span className="truncate text-2xs text-text-muted">{scopeLabel}</span>
      ) : null}
    </span>
  );

  if (inert) {
    return (
      <div className={cn('flex items-center gap-2 px-2', className)}>
        <Building2 aria-hidden="true" className="size-4 shrink-0 text-text-subtle" />
        {trigger}
      </div>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className={cn('h-auto max-w-64 justify-start gap-2 py-1', className)}
          aria-label={`Workspace: ${active.name}. Change tenant or brand scope`}
          iconLeft={<Building2 />}
          iconRight={<ChevronsUpDown className="text-text-subtle" />}
        >
          {trigger}
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-72">
        {canSwitchTenant ? (
          <>
            <DropdownMenuLabel>Companies</DropdownMenuLabel>
            {switchable.map((m) => (
              <DropdownMenuItem
                key={m.membershipId}
                onSelect={() => {
                  if (m.tenantId !== active.tenantId) onSwitchTenant?.(m.tenantId);
                }}
              >
                <Building2 aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate">{m.tenantName}</span>
                {m.tenantId === active.tenantId ? (
                  <Check aria-hidden="true" className="!text-primary" strokeWidth={3} />
                ) : null}
              </DropdownMenuItem>
            ))}
            {canScopeBrands ? <DropdownMenuSeparator /> : null}
          </>
        ) : null}

        {canScopeBrands ? (
          <>
            <DropdownMenuLabel>Brand scope</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => onBrandScopeChange?.([])}>
              <Layers aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">All brands</span>
              {brandScope.length === 0 ? (
                <Check aria-hidden="true" className="!text-primary" strokeWidth={3} />
              ) : null}
            </DropdownMenuItem>
            {brands.map((brand) => {
              const selected = brandScope.includes(brand.brandId);
              return (
                <DropdownMenuItem
                  key={brand.brandId}
                  // Multi-select: closing on every click makes picking three
                  // brands a three-trip journey.
                  onSelect={(event) => {
                    event.preventDefault();
                    onBrandScopeChange?.(
                      selected
                        ? brandScope.filter((id) => id !== brand.brandId)
                        : [...brandScope, brand.brandId],
                    );
                  }}
                >
                  <span className="min-w-0 flex-1 truncate">{brand.brandName}</span>
                  <span className="font-mono text-2xs text-text-subtle">{brand.brandCode}</span>
                  {selected ? (
                    <Check aria-hidden="true" className="!text-primary" strokeWidth={3} />
                  ) : null}
                </DropdownMenuItem>
              );
            })}
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
