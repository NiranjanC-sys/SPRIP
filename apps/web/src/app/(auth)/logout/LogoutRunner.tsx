'use client';

import * as React from 'react';
import Link from 'next/link';

import { useLogout } from '@/lib/api/queries/session';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';

/**
 * Sign-out.
 *
 * A page rather than a menu action, for two reasons. It is a state-changing
 * request, so it must be a POST — a `<Link>` that logs you out is a CSRF hole
 * and gets fired by link prefetchers. And the query cache must be cleared before
 * the user sees anything else, which needs a render pass under the provider.
 *
 * The mutation runs exactly once. React 18+ StrictMode double-invokes effects in
 * development; a ref guard is the standard fix and is cheaper than making the
 * endpoint idempotent for a case that only exists in dev.
 */
export function LogoutRunner() {
  const logout = useLogout();
  const fired = React.useRef(false);

  React.useEffect(() => {
    if (fired.current) return;
    fired.current = true;
    logout.mutate(undefined, {
      onSettled: () => {
        // Full navigation, not `router.push`: server components above this point
        // have already rendered with the authenticated session and would be
        // served from the client router cache otherwise.
        window.location.assign('/login');
      },
    });
    // `logout` is a stable mutation object; re-running on its identity would
    // defeat the guard's purpose.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col items-center gap-4 text-center">
      <Spinner size="xl" label="Signing out" className="text-text-subtle" />
      <h1 className="text-lg font-semibold tracking-tight text-text">Signing you out</h1>
      <p className="text-sm leading-relaxed text-text-muted">
        Clearing this session and everything cached in this tab.
      </p>
      {/* Shown only if the request stalls; the redirect normally lands first. */}
      <Button asChild variant="ghost" size="sm">
        <Link href="/login" prefetch={false}>
          Continue to sign in
        </Link>
      </Button>
    </div>
  );
}
