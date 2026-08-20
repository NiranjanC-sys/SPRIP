'use client';

import * as React from 'react';

import { ErrorState } from '@/components/data/states';

/**
 * Error boundary *inside* the shell.
 *
 * Without this file the nearest boundary is `app/error.tsx`, which sits above
 * `(app)/layout.tsx` — so one failing chart would tear down the nav, the tenant
 * switcher and the top bar along with it, and strand the user on a page whose
 * only exit is the browser's back button. Here the frame survives and only the
 * content area is replaced.
 */
export default function AppRouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    console.error('[app-route-error]', error.digest ?? '(no digest)', error);
  }, [error]);

  return (
    <div className="flex min-h-96 items-center justify-center p-6">
      <ErrorState
        error={error}
        title="This page could not be loaded"
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
