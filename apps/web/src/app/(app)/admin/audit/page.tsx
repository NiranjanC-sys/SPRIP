import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Audit log' };
export const dynamic = 'force-dynamic';

/** SCAFFOLD. Route, gate and navigation entry are wired. */
export default async function AdminAuditPage() {
  await requireAccess('/admin/audit');

  return (
    <>
      <PageHeader
        title="Audit log"
        breadcrumbs={[{ label: 'Administration' }, { label: 'Audit log' }]}
        description="Who did what, to which record, when — including every publication decision and every role change. Append-only; entries cannot be edited or removed from this screen."
      />
      <div className="p-4">
        <EmptyState
          title="Audit browser not built yet"
          description="This route, its role gate and its place in the navigation are wired. The audit query surface is delivered by the administration workstream."
        />
      </div>
    </>
  );
}
