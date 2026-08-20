import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Companies' };
export const dynamic = 'force-dynamic';

/**
 * SCAFFOLD. Route, gate and navigation entry are wired.
 *
 * Hard constraint for this whole section: the platform console administers
 * tenants but must never read tenant *business* data. A platform admin can see
 * that Northwind exists, is suspended, and has 41 users; they cannot see a
 * single one of Northwind's events, spend figures or results. The shell already
 * models this — `session.activeTenant` is null for a platform admin, so every
 * tenant-scoped query is disabled by construction.
 */
export default async function PlatformCompaniesPage() {
  await requireAccess('/platform/companies');

  return (
    <>
      <PageHeader
        title="Companies"
        breadcrumbs={[{ label: 'Platform' }, { label: 'Companies' }]}
        description="Tenant provisioning, lifecycle status and data region. Administrative metadata only — this console has no access to any tenant's commercial data."
      />
      <div className="p-4">
        <EmptyState
          title="Tenant console not built yet"
          description="This route, its role gate and its place in the navigation are wired. Provisioning is delivered by the platform workstream."
        />
      </div>
    </>
  );
}
