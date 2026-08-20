import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Reference data' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD. Route, gate and navigation entry are wired; editing is not built. */
export default async function TaxonomyPage() {
  await requireAccess('/data/taxonomy');

  return (
    <>
      <PageHeader
        title="Reference data"
        breadcrumbs={[{ label: 'Data' }, { label: 'Reference data' }]}
        description="Brands, campaigns, topics, regions and programme formats — the controlled vocabularies every filter, cohort definition and report groups by."
      />
      <div className="p-4">
        <EmptyState
          title="Reference data editor not built yet"
          description="This route, its role gate and its place in the navigation are wired. Taxonomy management is delivered by the data workstream."
        />
      </div>
    </>
  );
}
