import type { Metadata } from 'next';

import { AcceptInvitationForm } from './AcceptInvitationForm';

export const metadata: Metadata = {
  title: 'Accept invitation',
  // Belt and braces over the root layout's site-wide rule: this URL carries a
  // single-use credential in its query string and must never be indexed or
  // stored in a cache a proxy might share.
  robots: { index: false, follow: false, nocache: true, noarchive: true },
};

export const dynamic = 'force-dynamic';

export default async function AcceptInvitationPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const raw = params['token'];
  const token = (Array.isArray(raw) ? raw[0] : raw) ?? null;

  return <AcceptInvitationForm token={token} />;
}
