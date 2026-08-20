import { redirect } from 'next/navigation';

import { getServerSession } from '@/lib/auth/session.server';
import { landingRouteForRoles } from '@/lib/api/enums';

/**
 * `/` is a router, not a page.
 *
 * There is no single home screen: a Vendor Contributor's first useful surface is
 * their upload queue, a Finance Reviewer's is the ROI ledger, a Platform Admin
 * has no tenant data at all. `landingRouteForRoles` mirrors `_LANDING_ROUTES` in
 * packages/core enums.py exactly, so the two sides cannot drift into sending the
 * same user to different places.
 *
 * Rendered dynamically because the answer depends on the request's cookie; a
 * statically prerendered redirect would send everyone to the first role's route.
 */
export const dynamic = 'force-dynamic';

export default async function RootPage() {
  const session = await getServerSession();
  if (!session) redirect('/login');
  redirect(landingRouteForRoles(session.roles));
}
