import Link from 'next/link';

import { Button } from '@/components/ui/button';

/**
 * 404. Rendered inside the root layout but outside any route group, so it must
 * not assume the shell is mounted — an unauthenticated user hitting a bad URL
 * lands here too.
 *
 * The copy says nothing about whether the resource exists. "Not found" and "not
 * yours" have to look identical from the outside, or the 404 becomes a
 * membership oracle for record ids.
 */
export default function NotFound() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas p-6">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <p className="font-mono text-2xs font-medium uppercase tracking-widest text-text-subtle">
          Error 404
        </p>
        <h1 className="text-display font-semibold tracking-tight text-text">Page not found</h1>
        <p className="text-sm leading-relaxed text-text-muted">
          This page does not exist, or the link is out of date. If you followed a link from a report
          or an email, the underlying record may have been superseded by a newer data version.
        </p>
        <div className="mt-2 flex flex-wrap justify-center gap-2">
          <Button asChild>
            <Link href="/">Go to my dashboard</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
