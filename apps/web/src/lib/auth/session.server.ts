import 'server-only';

import { cookies, headers } from 'next/headers';
import { redirect } from 'next/navigation';

import { api } from '@/lib/api/client';
import { sessionSchema, type Session } from '@/lib/api/types';
import { UnauthorizedError } from '@/lib/api/errors';
import { DEV_SESSION_COOKIE, decodeDevSession } from '@/lib/api/mock/session';
import { buildSession } from '@/lib/api/mock/fixtures';
import { env } from '@/lib/env';
import { canAccessPath } from './routeAccess';
import type { Role } from '@/lib/api/enums';

/**
 * Server-side session resolution.
 *
 * This — not the middleware — is the authoritative Next.js-side check. Middleware
 * runs before the route is matched and is therefore a coarse gate; a layout that
 * calls `requireRoles()` is what guarantees a page body never renders for a user
 * who should not see it. The FastAPI layer independently enforces the same rules
 * on the data itself, which is the check that actually protects the rows.
 */

export async function getServerSession(): Promise<Session | null> {
  if (env.apiMock) {
    // Mock mode: the fixture cookie stands in for /auth/me. Gated on the flag,
    // so this branch is unreachable in a real deployment. See mock/session.ts.
    const store = await cookies();
    const dev = decodeDevSession(store.get(DEV_SESSION_COOKIE)?.value);
    return dev ? buildSession(dev.email, dev.roles) : null;
  }

  // Server components have no ambient cookie jar — forward the request's own
  // Cookie header so the API sees the caller's session, not none.
  const cookieHeader = (await headers()).get('cookie') ?? '';
  if (!cookieHeader) return null;

  try {
    return await api.get<Session>('/auth/me', {
      schema: sessionSchema,
      cookie: cookieHeader,
      suppressAuthRedirect: true,
      retries: 0,
    });
  } catch (error) {
    if (error instanceof UnauthorizedError) return null;
    // Fail closed. A flaky API must not render an authenticated shell.
    return null;
  }
}

export async function getServerRoles(): Promise<Role[]> {
  const session = await getServerSession();
  return session?.roles ?? [];
}

/**
 * Throws the Next.js `forbidden`-style redirect decision back to the caller as a
 * boolean, rather than redirecting here — layouts differ in whether they want
 * `/forbidden` or an inline `ForbiddenState`.
 */
export async function canAccess(pathname: string): Promise<boolean> {
  const roles = await getServerRoles();
  return canAccessPath(pathname, roles);
}

/**
 * The per-route server check. Every page under `(app)` calls this with its own
 * literal path.
 *
 * Passing the path explicitly rather than sniffing it from a middleware-injected
 * header is deliberate: a page with no guard then shows up as a missing call in
 * a two-second grep, instead of silently inheriting whatever a header happened to
 * say. It also means the check keeps working if the middleware matcher is ever
 * narrowed by accident.
 *
 * Redirects to `/forbidden` rather than rendering an inline 403, so the user
 * cannot end up staring at a permission error inside a page shell that implies
 * the content is one refresh away.
 */
export async function requireAccess(pathname: string): Promise<Session> {
  const session = await getServerSession();
  if (!session) redirect(`/login?returnTo=${encodeURIComponent(pathname)}`);
  if (!canAccessPath(pathname, session.roles)) redirect('/forbidden');
  return session;
}
