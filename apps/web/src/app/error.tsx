'use client';

import * as React from 'react';

import { ErrorState } from '@/components/data/states';

/**
 * Route-level error boundary. Catches render and data errors below the root
 * layout, so the shell and the nav survive a page blowing up.
 *
 * `digest` is Next's server-side error id — the only thing that correlates this
 * screen to a stack trace when the message itself has been scrubbed in
 * production. It is surfaced through `ErrorState`'s reference line.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    // Reaching this boundary is always a defect. Log the digest so the browser
    // console gives support something to search for.
    console.error('[route-error]', error.digest ?? '(no digest)', error);
  }, [error]);

  return (
    <div className="flex min-h-96 items-center justify-center p-6">
      <ErrorState
        error={error}
        title="This page could not be rendered"
        description={
          error.digest
            ? `Something failed while building this view. Quote reference ${error.digest} to support.`
            : 'Something failed while building this view. Retrying is safe — nothing was changed.'
        }
        onRetry={reset}
      />
    </div>
  );
}
