import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { requireAccess } from '@/lib/auth/session.server';
import { TemplateList } from './TemplateList';

export const metadata: Metadata = { title: 'Templates' };
export const dynamic = 'force-dynamic';

export default async function VendorTemplatesPage() {
  await requireAccess('/vendor/templates');

  return (
    <>
      <PageHeader
        title="Templates"
        breadcrumbs={[{ label: 'Submissions' }, { label: 'Templates' }]}
        description="Current file specifications and data dictionaries. Submit against the version shown here — batches are validated against the spec that was current when the upload started."
      />
      <TemplateList />
    </>
  );
}
