'use client';

import * as React from 'react';
import Link from 'next/link';
import { ChevronsUpDown, LogOut, Settings, ShieldCheck } from 'lucide-react';

import type { Session } from '@/lib/api/types';
import { humanizeEnum } from '@/lib/utils';
import { formatDateTime } from '@/lib/formatters';
import { Avatar } from '@/components/ui/avatar';
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
 * Identity, effective roles, and the way out.
 *
 * The roles are listed rather than summarised because "why can I not see the
 * finance module" is a support ticket this menu can answer on its own. Sign-out
 * is a link to `/logout` rather than an in-place mutation so it survives a dead
 * session — the one moment you most need it to work is the moment the API is
 * refusing everything.
 */

export interface UserMenuProps {
  session: Session;
}

export function UserMenu({ session }: UserMenuProps) {
  const { user, roles, activeTenant } = session;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-auto gap-2 py-1 pl-1 pr-2"
          aria-label={`Account menu for ${user.displayName}`}
        >
          <Avatar name={user.displayName} size="sm" />
          <span className="hidden min-w-0 flex-col items-start leading-tight sm:flex">
            <span className="max-w-36 truncate text-sm font-medium text-text">{user.displayName}</span>
            <span className="max-w-36 truncate text-2xs text-text-muted">
              {roles.length > 0 ? humanizeEnum(roles[0] ?? '') : 'No role assigned'}
              {roles.length > 1 ? ` +${roles.length - 1}` : ''}
            </span>
          </span>
          <ChevronsUpDown aria-hidden="true" className="size-3.5 text-text-subtle" />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-72">
        <div className="px-2 py-1.5">
          <p className="truncate text-sm font-semibold text-text">{user.displayName}</p>
          <p className="truncate text-xs text-text-muted">{user.email}</p>
          {activeTenant ? (
            <p className="mt-1 truncate text-2xs text-text-subtle">{activeTenant.name}</p>
          ) : null}
        </div>

        <DropdownMenuSeparator />

        <DropdownMenuLabel>Effective roles</DropdownMenuLabel>
        <div className="flex flex-wrap gap-1 px-2 pb-2">
          {roles.length === 0 ? (
            <span className="text-xs text-text-muted">None assigned yet.</span>
          ) : (
            roles.map((role) => (
              <Badge key={role} variant="outline" size="sm">
                {humanizeEnum(role)}
              </Badge>
            ))
          )}
        </div>

        <DropdownMenuSeparator />

        <DropdownMenuItem asChild>
          <Link href="/settings">
            <Settings aria-hidden="true" />
            Settings
          </Link>
        </DropdownMenuItem>

        <div className="px-2 py-1.5 text-2xs text-text-subtle">
          <span className="flex items-center gap-1.5">
            <ShieldCheck aria-hidden="true" className="size-3" />
            {user.mfaEnrolled ? 'Two-factor enabled' : 'Two-factor not enabled'}
          </span>
          {user.lastLoginAt ? (
            <span className="mt-0.5 block">Last sign-in {formatDateTime(user.lastLoginAt)}</span>
          ) : null}
        </div>

        <DropdownMenuSeparator />

        <DropdownMenuItem asChild destructive>
          {/* A real navigation: `/logout` clears the cookie server-side and then
              redirects, which still works when every API call is 401ing. */}
          <Link href="/logout" prefetch={false}>
            <LogOut aria-hidden="true" />
            Sign out
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
