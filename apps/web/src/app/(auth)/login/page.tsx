import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { getServerSession } from '@/lib/auth/session.server';
import { landingRouteForRoles } from '@/lib/api/enums';
import { isSafeReturnPath } from '@/lib/utils';
import { LoginForm } from './LoginForm';

export const metadata: Metadata = { title: 'Sign in' };

/** Depends on the request cookie; there is nothing here to prerender. */
export const dynamic = 'force-dynamic';

function first(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) return value[0] ?? null;
  return value ?? null;
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;

  // Sanitised on the server, before it reaches a client component. `returnTo`
  // is attacker-controlled by construction — it arrives in a link — so it is
  // validated as a same-origin, path-only value here and treated as trusted
  // nowhere else. `isSafeReturnPath` rejects `//evil.com`, `/\evil.com` and any
  // scheme-bearing value; anything it refuses becomes `null`, not a redirect.
  const candidate = first(params['returnTo']);
  const returnTo = isSafeReturnPath(candidate) ? candidate : null;
  const reason = first(params['reason']);

  // Already signed in: bounce rather than showing a form that would sign the
  // user in as themselves again. `returnTo` still wins, so a stale /login link
  // in a bookmark still lands on the intended deep page.
  const session = await getServerSession();
  if (session) redirect(returnTo ?? landingRouteForRoles(session.roles));

  return <LoginForm returnTo={returnTo} reason={reason} />;
}
