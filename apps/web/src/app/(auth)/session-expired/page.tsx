import type { Metadata } from 'next';
import Link from 'next/link';
import { Clock } from 'lucide-react';

import { isSafeReturnPath } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Callout } from '@/components/ui/callout';

export const metadata: Metadata = { title: 'Session expired' };

export const dynamic = 'force-dynamic';

/**
 * A distinct screen from `/login`, deliberately.
 *
 * Being dropped onto a sign-in form mid-task reads as a bug or a phish. Naming
 * what happened, and carrying the page the user was on into the sign-in link, is
 * the difference between "the app logged me out" and "the app lost my work".
 *
 * The unsaved-work warning is honest: this product has long-running forms
 * (scenario definitions, review notes) and inactivity timeouts are short in
 * regulated deployments.
 */
export default async function SessionExpiredPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const raw = params['returnTo'];
  const candidate = (Array.isArray(raw) ? raw[0] : raw) ?? null;
  // Validated here so the link below can never be turned into an open redirect
  // by whoever crafted the URL that landed the user on this page.
  const returnTo = isSafeReturnPath(candidate) ? candidate : null;

  const signInHref = returnTo
    ? `/login?reason=expired&returnTo=${encodeURIComponent(returnTo)}`
    : '/login?reason=expired';

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <span
          aria-hidden="true"
          className="flex size-10 items-center justify-center rounded-full bg-info-soft text-info"
        >
          <Clock className="size-5" />
        </span>
        <h1 className="text-display font-semibold tracking-tight text-text">Your session ended</h1>
        <p className="text-sm leading-relaxed text-text-muted">
          You were signed out after a period of inactivity. This is a security control, not an error
          — sessions in this workspace are deliberately short.
        </p>
      </div>

      <Button asChild size="lg" block>
        <Link href={signInHref} prefetch={false}>
          Sign in again
        </Link>
      </Button>

      {returnTo ? (
        <Callout tone="neutral">
          You will be returned to <code className="font-mono">{returnTo}</code> after signing in.
        </Callout>
      ) : null}

      <p className="text-xs leading-relaxed text-text-subtle">
        Anything you had typed but not saved is gone. Draft scenarios and submitted files are
        unaffected.
      </p>
    </div>
  );
}
