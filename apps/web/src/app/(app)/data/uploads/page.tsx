import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { requireAccess } from '@/lib/auth/session.server';
import { UploadsWorkspace } from './UploadsWorkspace';

export const metadata: Metadata = { title: 'Uploads' };
export const dynamic = 'force-dynamic';

export default async function DataUploadsPage() {
  await requireAccess('/data/uploads');

  return (
    <>
      <PageHeader
        title="Uploads"
        breadcrumbs={[{ label: 'Data' }, { label: 'Uploads' }]}
        description="Submit a dataset and follow it through validation. A batch only becomes part of a data version once every blocking issue is cleared."
      />
      <UploadsWorkspace />
    </>
  );
}
