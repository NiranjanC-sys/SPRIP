import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Budget optimiser' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD — owned by the dashboards workstream. See portfolio/page.tsx. */
export default async function BudgetPage() {
  await requireAccess('/budget');

  return (
    <>
      <PageHeader
        title="Budget optimiser"
        breadcrumbs={[{ label: 'Plan' }, { label: 'Budget optimiser' }]}
        description="Allocate spend across brands, formats and regions under stated constraints — with allocations to low-evidence segments capped rather than maximised."
      />
      <div className="p-4">
        <EmptyState
          title="Budget optimiser not built yet"
          description="This route, its role gate and its place in the navigation are wired. The allocation model is delivered by the analytics workstream."
        />
      </div>
    </>
  );
}
