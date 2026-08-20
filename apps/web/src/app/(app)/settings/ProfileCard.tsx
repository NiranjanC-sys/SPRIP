'use client';

import Link from 'next/link';
import { ShieldCheck, ShieldOff } from 'lucide-react';

import { useSession } from '@/lib/api/queries/session';
import { humanizeEnum } from '@/lib/utils';
import { formatDateTime } from '@/lib/formatters';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { AuthProviderKind } from '@/lib/api/enums';

/**
 * Read-only account summary.
 *
 * Nothing here is editable, and that is the design. Roles and brand scope are
 * assigned by an administrator and resolved server-side on every request; a
 * self-service control would either be a lie (it cannot take effect) or a
 * privilege-escalation surface. Where a user needs a change, the page says who
 * to ask.
 */
export function ProfileCard() {
  const { data: session, isPending } = useSession();

  if (isPending || !session) {
    return (
      <Card>
        <CardHeader bordered>
          <CardTitle>Account</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-4 w-56" label="Loading account" />
          <Skeleton className="h-4 w-72" />
          <Skeleton className="h-4 w-40" />
        </CardContent>
      </Card>
    );
  }

  const { user, roles, activeTenant, brandScopes } = session;
  const federated = session.authProvider === AuthProviderKind.OIDC;

  return (
    <Card>
      <CardHeader bordered>
        <CardTitle>Account</CardTitle>
        <CardDescription>
          Roles and scope are set by your organisation administrator and cannot be changed here.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid gap-3 sm:grid-cols-2">
          <Field label="Name">{user.displayName}</Field>
          <Field label="Email">{user.email}</Field>
          <Field label="Workspace">{activeTenant?.name ?? 'Platform console'}</Field>
          <Field label="Last sign-in">{formatDateTime(user.lastLoginAt)}</Field>
          <Field label="Roles">
            <span className="flex flex-wrap gap-1">
              {roles.length === 0 ? (
                <span className="text-text-muted">None assigned</span>
              ) : (
                roles.map((role) => (
                  <Badge key={role} variant="outline">
                    {humanizeEnum(role)}
                  </Badge>
                ))
              )}
            </span>
          </Field>
          <Field label="Brand scope">
            {brandScopes.length === 0 ? (
              // Empty scope means "all brands in the workspace", which is the
              // opposite of what an empty list looks like. Say so explicitly.
              <span className="text-text-muted">All brands in this workspace</span>
            ) : (
              <span className="flex flex-wrap gap-1">
                {brandScopes.map((scope) => (
                  <Badge key={scope.brandId} variant="outline">
                    {scope.brandName}
                  </Badge>
                ))}
              </span>
            )}
          </Field>
        </dl>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-surface-sunken px-3 py-2.5">
          <div className="flex items-center gap-2 text-sm">
            <span
              aria-hidden="true"
              className={user.mfaEnrolled ? 'text-positive' : 'text-warning'}
            >
              {user.mfaEnrolled ? <ShieldCheck className="size-4" /> : <ShieldOff className="size-4" />}
            </span>
            <span className="text-text">
              Two-factor authentication is {user.mfaEnrolled ? 'enabled' : 'not enabled'}
            </span>
          </div>
          {federated ? (
            <span className="text-xs text-text-muted">Managed by your identity provider</span>
          ) : (
            <span className="text-xs text-text-muted">
              Contact your administrator to change this
            </span>
          )}
        </div>

        <div>
          <Button asChild variant="secondary" size="sm">
            <Link href="/logout" prefetch={false}>
              Sign out
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-2xs uppercase tracking-wide text-text-subtle">{label}</dt>
      <dd className="text-sm text-text">{children}</dd>
    </div>
  );
}
