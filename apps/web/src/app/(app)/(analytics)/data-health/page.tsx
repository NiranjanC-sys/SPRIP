import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Data & model health' };
export const dynamic = 'force-dynamic';

/**
 * SCAFFOLD — owned by the dashboards workstream. See portfolio/page.tsx.
 *
 * Note for whoever builds this: `InsufficientEvidenceState` links here as its
 * "How evidence is graded" destination, so this page needs a stable anchor
 * explaining the hard gates. Changing that contract means changing
 * `methodologyHref` in components/data/states.tsx too.
 */
export default async function DataHealthPage() {
  await requireAccess('/data-health');

  return (
    <>
      <PageHeader
        title="Data & model health"
        breadcrumbs={[{ label: 'Data' }, { label: 'Data & model health' }]}
        description="Feed freshness, coverage, identity match rates, model run status and drift — the inputs that decide what any number on this platform is allowed to claim."
      />
      <div className="p-4">
        <EmptyState
          title="Health surface not built yet"
          description="This route, its role gate and its place in the navigation are wired. Freshness, coverage and run monitoring are delivered by the analytics workstream."
        />
      </div>
    </>
  );
}
