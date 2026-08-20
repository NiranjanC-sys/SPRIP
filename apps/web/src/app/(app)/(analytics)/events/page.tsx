import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Events' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD — owned by the dashboards workstream. See portfolio/page.tsx. */
export default async function EventsPage() {
  await requireAccess('/events');

  return (
    <>
      <PageHeader
        title="Events"
        breadcrumbs={[{ label: 'Analyze' }, { label: 'Events' }]}
        description="Every speaker programme, the attendee cohort it created, the matched control it was measured against, and the grade that cohort supports."
      />
      <div className="p-4">
        <EmptyState
          title="Events surface not built yet"
          description="This route, its role gate and its place in the navigation are wired. The event explorer is delivered by the analytics workstream."
        />
      </div>
    </>
  );
}
