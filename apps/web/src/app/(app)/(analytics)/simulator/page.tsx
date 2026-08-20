import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Scenario simulator' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD — owned by the dashboards workstream. See portfolio/page.tsx. */
export default async function SimulatorPage() {
  await requireAccess('/simulator');

  return (
    <>
      <PageHeader
        title="Scenario simulator"
        breadcrumbs={[{ label: 'Plan' }, { label: 'Scenario simulator' }]}
        description="Forecast the effect of a programme mix before committing budget. Forecasts inherit the evidence grade of the history they are fitted on."
      />
      <div className="p-4">
        <EmptyState
          title="Simulator not built yet"
          description="This route, its role gate and its place in the navigation are wired. The scenario engine is delivered by the analytics workstream."
        />
      </div>
    </>
  );
}
