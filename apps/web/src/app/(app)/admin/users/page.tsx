import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Users & roles' };
export const dynamic = 'force-dynamic';

/**
 * SCAFFOLD. Route, gate and navigation entry are wired.
 *
 * Whoever builds this: there is no self-signup anywhere in the product, so the
 * invitation flow implemented here is the *only* way an account comes into
 * existence. `/accept-invitation` is the other half and already works.
 */
export default async function AdminUsersPage() {
  await requireAccess('/admin/users');

  return (
    <>
      <PageHeader
        title="Users & roles"
        breadcrumbs={[{ label: 'Administration' }, { label: 'Users & roles' }]}
        description="Invitations, role assignment and brand scoping. Roles are resolved from this table on every request — never from a token claim."
      />
      <div className="p-4">
        <EmptyState
          title="User administration not built yet"
          description="This route, its role gate and its place in the navigation are wired. Invitations and role assignment are delivered by the administration workstream."
        />
      </div>
    </>
  );
}
