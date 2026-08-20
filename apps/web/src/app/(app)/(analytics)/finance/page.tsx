import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Finance & ROI' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD — owned by the dashboards workstream. See portfolio/page.tsx. */
export default async function FinancePage() {
  await requireAccess('/finance');

  return (
    <>
      <PageHeader
        title="Finance & ROI"
        breadcrumbs={[{ label: 'Analyze' }, { label: 'Finance & ROI' }]}
        description="Fully loaded programme cost, attributed benefit, benefit-cost ratio and net return — every figure resolving to a named finance version."
      />
      <div className="p-4">
        <EmptyState
          title="Finance surface not built yet"
          description="This route, its role gate and its place in the navigation are wired. The ROI ledger is delivered by the analytics workstream."
        />
      </div>
    </>
  );
}
