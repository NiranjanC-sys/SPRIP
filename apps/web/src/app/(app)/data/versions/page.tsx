import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Data versions' };
export const dynamic = 'force-dynamic';

/**
 * SCAFFOLD. Route, gate and navigation entry are wired.
 *
 * `LineageChip` links here for the `data_version` element of the lineage tuple
 * (tenant · data version · run · model version · finance version), so the detail
 * route this page will eventually own is already referenced elsewhere.
 */
export default async function DataVersionsPage() {
  await requireAccess('/data/versions');

  return (
    <>
      <PageHeader
        title="Data versions"
        breadcrumbs={[{ label: 'Data' }, { label: 'Data versions' }]}
        description="Immutable snapshots of the input data. Every published figure resolves to exactly one of these, which is what makes a number from six months ago reproducible today."
      />
      <div className="p-4">
        <EmptyState
          title="Version browser not built yet"
          description="This route, its role gate and its place in the navigation are wired. Snapshot comparison is delivered by the data workstream."
        />
      </div>
    </>
  );
}
