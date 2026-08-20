import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Company' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD. Route, gate and navigation entry are wired. */
export default async function AdminCompanyPage() {
  await requireAccess('/admin/company');

  return (
    <>
      <PageHeader
        title="Company"
        breadcrumbs={[{ label: 'Administration' }, { label: 'Company' }]}
        description="Workspace profile, reporting currency, data region and feature flags. Changing the reporting currency re-denominates every stored financial figure, so it is versioned rather than edited in place."
      />
      <div className="p-4">
        <EmptyState
          title="Company settings not built yet"
          description="This route, its role gate and its place in the navigation are wired. Tenant configuration is delivered by the administration workstream."
        />
      </div>
    </>
  );
}
