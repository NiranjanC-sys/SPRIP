import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Operations' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD. Route, gate and navigation entry are wired. See platform/companies. */
export default async function PlatformOperationsPage() {
  await requireAccess('/platform/operations');

  return (
    <>
      <PageHeader
        title="Operations"
        breadcrumbs={[{ label: 'Platform' }, { label: 'Operations' }]}
        description="Job queues, worker health, model release state and per-tenant run status. Counts and timings only — never the payloads those jobs processed."
      />
      <div className="p-4">
        <EmptyState
          title="Operations console not built yet"
          description="This route, its role gate and its place in the navigation are wired. Queue and worker monitoring is delivered by the platform workstream."
        />
      </div>
    </>
  );
}
