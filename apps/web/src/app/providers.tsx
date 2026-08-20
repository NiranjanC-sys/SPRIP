'use client';

import * as React from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from 'next-themes';
import { Toaster } from 'sonner';

import { createQueryClient } from '@/lib/api/queryClient';
import { env } from '@/lib/env';
import { TooltipProvider } from '@/components/ui/tooltip';

/**
 * Client-side providers.
 *
 * The QueryClient is created in state rather than at module scope: a module-level
 * client is shared across requests in a Node server and would leak one user's
 * cached tenant data into another user's render.
 *
 * `attribute="data-theme"` matches the selectors in globals.css, and
 * `disableTransitionOnChange` stops every bordered surface animating its colour
 * for 200ms when the theme flips — which on a page of 400 table cells reads as a
 * stutter, not a transition.
 */

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(createQueryClient);

  // Dev fixture mode. `env.apiMock` folds to `false` at build time in any real
  // deployment, so this whole branch — and the mock module — is dropped.
  const [mockReady, setMockReady] = React.useState(!env.apiMock);
  React.useEffect(() => {
    if (!env.apiMock) return;
    let cancelled = false;
    void import('@/lib/api/mock').then(({ installMockApi }) => {
      installMockApi();
      if (!cancelled) setMockReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <ThemeProvider
      attribute="data-theme"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      storageKey="sr.theme"
    >
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={200} skipDelayDuration={400}>
          {/* Holding the first paint until the fetch patch is installed avoids a
              burst of real network calls that would 404 in fixture mode. */}
          {mockReady ? children : null}
          <Toaster
            position="bottom-right"
            closeButton
            toastOptions={{
              classNames: {
                toast:
                  'group rounded-md border border-border bg-surface-raised text-text shadow-lg text-sm',
                description: 'text-text-muted',
                actionButton: 'bg-primary text-primary-fg',
                cancelButton: 'bg-surface-sunken text-text-muted',
              },
            }}
          />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
