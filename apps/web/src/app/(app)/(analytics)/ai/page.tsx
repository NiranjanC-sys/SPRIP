import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Ask the data' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD — owned by the dashboards workstream. See portfolio/page.tsx. */
export default async function AskTheDataPage() {
  await requireAccess('/ai');

  return (
    <>
      <PageHeader
        title="Ask the data"
        breadcrumbs={[{ label: 'Plan' }, { label: 'Ask the data' }]}
        description="Natural-language questions answered only from governed results, every claim carrying a citation to the figure it came from — or an explicit refusal."
      />
      <div className="p-4">
        <EmptyState
          title="Assistant not built yet"
          description="This route, its role gate and its place in the navigation are wired. The grounded answering surface is delivered by the analytics workstream."
        />
      </div>
    </>
  );
}
