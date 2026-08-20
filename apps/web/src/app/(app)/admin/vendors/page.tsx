import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Vendors' };
export const dynamic = 'force-dynamic';

/**
 * SCAFFOLD. Route, gate and navigation entry are wired.
 *
 * PLAN_REVIEW F-8 applies to everything configured here: a vendor may be granted
 * submission rights to a dataset, never read access to prescription outcomes.
 * The permission model on this page must not be able to express the latter.
 */
export default async function AdminVendorsPage() {
  await requireAccess('/admin/vendors');

  return (
    <>
      <PageHeader
        title="Vendors"
        breadcrumbs={[{ label: 'Administration' }, { label: 'Vendors' }]}
        description="Contributing agencies, the datasets each may submit, and the brands they may submit against."
      />
      <div className="p-4">
        <EmptyState
          title="Vendor administration not built yet"
          description="This route, its role gate and its place in the navigation are wired. Vendor onboarding is delivered by the administration workstream."
        />
      </div>
    </>
  );
}
