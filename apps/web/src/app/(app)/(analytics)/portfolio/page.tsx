import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { EmptyState } from '@/components/data/states';
import { requireAccess } from '@/lib/auth/session.server';

export const metadata: Metadata = { title: 'Portfolio' };
export const dynamic = 'force-dynamic';

/**
 * SCAFFOLD — owned by the dashboards workstream, not by the foundation.
 *
 * Everything below the `requireAccess` call is placeholder. Replace the
 * `<EmptyState>` with the real content; keep the guard, the `<PageHeader>` and
 * the breadcrumb shape, since the shell's landmark and heading structure depend
 * on exactly one `<h1>` coming from `PageHeader`.
 */
export default async function PortfolioPage() {
  await requireAccess('/portfolio');

  return (
    <>
      <PageHeader
        title="Portfolio"
        breadcrumbs={[{ label: 'Analyze' }, { label: 'Portfolio' }]}
        description="Reach, incremental lift and return on investment across every brand and campaign in scope, with the evidence grade that each figure earned."
      />
      <div className="p-4">
        <EmptyState
          title="Portfolio surface not built yet"
          description="This route, its role gate and its place in the navigation are wired. The dashboard itself is delivered by the analytics workstream."
        />
      </div>
    </>
  );
}
