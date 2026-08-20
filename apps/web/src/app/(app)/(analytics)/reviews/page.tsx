import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Review queue' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD — owned by the dashboards workstream. See portfolio/page.tsx. */
export default async function ReviewsPage() {
  await requireAccess('/reviews');

  return (
    <>
      <PageHeader
        title="Review queue"
        breadcrumbs={[{ label: 'Analyze' }, { label: 'Review queue' }]}
        description="Results awaiting compliance and finance sign-off before they may be published. Nothing leaves DRAFT without a recorded decision."
      />
      <div className="p-4">
        <EmptyState
          title="Review queue not built yet"
          description="This route, its role gate and its place in the navigation are wired. The approval workflow is delivered by the analytics workstream."
        />
      </div>
    </>
  );
}
