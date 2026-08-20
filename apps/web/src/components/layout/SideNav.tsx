'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';

import type { Role } from '@/lib/api/enums';
import { cn } from '@/lib/utils';
import { IconButton } from '@/components/ui/icon-button';
import { Tooltip } from '@/components/ui/tooltip';
import { ProductMark } from './ProductMark';
import {
  isNavItemActive,
  visibleFooterNavigation,
  visibleNavigation,
  type NavItem,
} from './navigation';

/**
 * The primary rail.
 *
 * Collapsed mode keeps the icons and drops the labels, with a tooltip carrying
 * the name — a rail that disappears entirely forces a mode switch every time you
 * need to move, which on a product people live in all day is worse than the
 * 56px it costs to keep.
 *
 * Markup is `<nav>` → `<ul>` → `<li>` rather than a stack of divs, so a screen
 * reader announces "list, 5 items" and the user can skip the whole region. The
 * active item carries `aria-current="page"`; the visual bar is decoration.
 */

export interface SideNavProps {
  roles: readonly Role[];
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  /** Set when rendered inside the mobile drawer, which has its own dismissal. */
  inSheet?: boolean;
  onNavigate?: () => void;
}

export function SideNav({
  roles,
  collapsed,
  onCollapsedChange,
  inSheet = false,
  onNavigate,
}: SideNavProps) {
  const pathname = usePathname();
  const groups = React.useMemo(() => visibleNavigation(roles), [roles]);
  const footer = React.useMemo(() => visibleFooterNavigation(roles), [roles]);
  const isCollapsed = collapsed && !inSheet;

  return (
    <nav
      aria-label="Primary"
      className={cn(
        'flex h-full flex-col bg-nav-bg text-nav-fg',
        isCollapsed ? 'w-14' : 'w-60',
        !inSheet && 'transition-[width] duration-200 ease-out-quint motion-reduce:transition-none',
      )}
    >
      <div
        className={cn(
          'flex h-14 shrink-0 items-center gap-2 border-b border-white/10',
          isCollapsed ? 'justify-center px-2' : 'px-3',
        )}
      >
        <ProductMark collapsed={isCollapsed} />
      </div>

      <div className="scroll-thin flex-1 overflow-y-auto overflow-x-hidden py-3">
        {groups.map((group) => (
          <div key={group.id} className="mb-4 last:mb-0">
            {group.label && !isCollapsed ? (
              <h2 className="px-3 pb-1.5 text-2xs font-semibold uppercase tracking-wider text-nav-fg/55">
                {group.label}
              </h2>
            ) : null}
            <ul className={cn('flex flex-col gap-0.5', isCollapsed ? 'px-2' : 'px-2')}>
              {group.items.map((item) => (
                <li key={item.id}>
                  <NavLink
                    item={item}
                    active={isNavItemActive(item, pathname)}
                    collapsed={isCollapsed}
                    onNavigate={onNavigate}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="shrink-0 border-t border-white/10 p-2">
        <ul className="flex flex-col gap-0.5">
          {footer.map((item) => (
            <li key={item.id}>
              <NavLink
                item={item}
                active={isNavItemActive(item, pathname)}
                collapsed={isCollapsed}
                onNavigate={onNavigate}
              />
            </li>
          ))}
        </ul>

        {!inSheet ? (
          <div className={cn('mt-1 flex', isCollapsed ? 'justify-center' : 'justify-end')}>
            <IconButton
              label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
              variant="nav"
              size="sm"
              onClick={() => onCollapsedChange(!collapsed)}
              aria-expanded={!collapsed}
            >
              {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
            </IconButton>
          </div>
        ) : null}
      </div>
    </nav>
  );
}

function NavLink({
  item,
  active,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const link = (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'group relative flex items-center gap-2.5 rounded-md text-sm font-medium outline-offset-2',
        collapsed ? 'justify-center px-0 py-2' : 'px-2.5 py-1.5',
        active
          ? 'bg-nav-active-bg text-nav-fg-active'
          : 'text-nav-fg hover:bg-nav-active-bg/60 hover:text-nav-fg-active',
      )}
    >
      {active ? (
        <span
          aria-hidden="true"
          className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-primary"
        />
      ) : null}
      <item.icon aria-hidden="true" className="size-4 shrink-0" />
      {collapsed ? (
        <span className="sr-only">{item.label}</span>
      ) : (
        <span className="truncate">{item.label}</span>
      )}
    </Link>
  );

  if (!collapsed) return link;

  return (
    <Tooltip content={item.label} side="right">
      {link}
    </Tooltip>
  );
}
