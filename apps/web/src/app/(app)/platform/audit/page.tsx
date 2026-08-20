import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Platform audit' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD. Route, gate and navigation entry are wired. See platform/companies. */
export default async function PlatformAuditPage() {
  await requireAccess('/platform/audit');

  return (
    <>
      <PageHeader
        title="Platform audit"
        breadcrumbs={[{ label: 'Platform' }, { label: 'Platform audit' }]}
        description="Cross-tenant administrative actions: provisioning, suspension, support access and impersonation. Separate from each tenant's own audit log, and never merged into it."
      />
      <div className="p-4">
        <EmptyState
          title="Platform audit browser not built yet"
          description="This route, its role gate and its place in the navigation are wired. Cross-tenant audit is delivered by the platform workstream."
        />
      </div>
    </>
  );
}
