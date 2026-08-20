import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Identity resolution' };
export const dynamic = 'force-dynamic';

/**
 * SCAFFOLD. Route, gate and navigation entry are wired; the adjudication queue
 * is not built.
 *
 * Constraint for whoever builds it (PLAN_REVIEW F-6): this surface may show
 * match candidates and their evidence, but it must never display an
 * outcome or score at HCP grain. Identity work is a data-quality task, not a
 * window into individual prescriber behaviour.
 */
export default async function IdentityResolutionPage() {
  await requireAccess('/data/identity');

  return (
    <>
      <PageHeader
        title="Identity resolution"
        breadcrumbs={[{ label: 'Data' }, { label: 'Identity resolution' }]}
        description="Review and adjudicate ambiguous HCP matches. Every decision is recorded and replayable against the data version it was made in."
      />
      <div className="p-4">
        <EmptyState
          title="Adjudication queue not built yet"
          description="This route, its role gate and its place in the navigation are wired. The match review workflow is delivered by the data workstream."
        />
      </div>
    </>
  );
}
