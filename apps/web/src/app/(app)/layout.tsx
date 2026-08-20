import { redirect } from 'next/navigation';

import { AppShell } from '@/components/layout/AppShell';
import { getServerSession } from '@/lib/auth/session.server';
import { SessionBoundary } from './SessionBoundary';

/**
 * The authenticated boundary.
 *
 * This is the authoritative Next-side gate, not `middleware.ts`. Middleware runs
 * on a cookie's *presence* at the edge and is a cheap first pass; this layout
 * resolves the session against the application database (`/auth/me`) and refuses
 * to render a single child if that fails. The FastAPI layer independently
 * enforces the same rules on every row — three checks, and only the last one
 * actually protects data.
 *
 * `force-dynamic` is required rather than incidental: a statically rendered
 * shell would bake one user's tenant name, roles and nav tree into the build
 * output and serve it to everyone.
 */
export const dynamic = 'force-dynamic';

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await getServerSession();

  // No `returnTo` here. This layout wraps every authenticated route, so the
  // pathname is not available to it without `headers()` — and the middleware,
  // which does see the path, has already attached one on the way in. Adding a
  // second, wrong `returnTo` would overwrite the correct one.
  if (!session) redirect('/login');

  return (
    <SessionBoundary session={session}>
      <AppShell session={session}>{children}</AppShell>
    </SessionBoundary>
  );
}
