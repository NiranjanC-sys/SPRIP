'use client';

import '@/styles/globals.css';

/**
 * Last-resort boundary. Replaces the root layout, so it must ship its own
 * <html>/<body> and cannot rely on anything the providers set up — no theme
 * context, no query client, no fonts.
 *
 * Because next-themes never ran, `data-theme` is absent and only the
 * `prefers-color-scheme` block in globals.css applies. That block is written to
 * be correct on its own, so this screen still respects the OS setting.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="min-h-dvh bg-canvas font-sans text-text antialiased">
        <main className="flex min-h-dvh items-center justify-center p-6">
          <div className="flex max-w-md flex-col items-center gap-4 text-center">
            <h1 className="text-display font-semibold tracking-tight">Something went badly wrong</h1>
            <p className="text-sm leading-relaxed text-text-muted">
              The application failed to start. No data was changed. Reloading usually clears it; if
              it does not, contact support.
            </p>
            {error.digest ? (
              <p className="text-2xs text-text-subtle">
                Reference <code className="font-mono">{error.digest}</code>
              </p>
            ) : null}
            <button
              type="button"
              onClick={reset}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-fg transition-colors hover:bg-primary-hover"
            >
              Reload the application
            </button>
          </div>
        </main>
      </body>
    </html>
  );
}
