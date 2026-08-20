import type { Metadata } from 'next';

import { PageHeader } from '@/components/layout/PageHeader';
import { Callout } from '@/components/ui/callout';
import { requireAccess } from '@/lib/auth/session.server';
import { UploadsWorkspace } from '../../data/uploads/UploadsWorkspace';

export const metadata: Metadata = { title: 'My submissions' };
export const dynamic = 'force-dynamic';

/**
 * The vendor portal's submission surface.
 *
 * Same workspace component as `/data/uploads`, different framing — and, more
 * importantly, a different API scope. PLAN_REVIEW F-8: a vendor never sees
 * prescription outcomes, so this page is a *submission* surface only. It shows
 * what the vendor sent and how it validated; it shows nothing about what the
 * data was subsequently used to measure. That boundary is enforced by the API on
 * the vendor's own token, not by hiding columns here.
 */
export default async function VendorUploadsPage() {
  await requireAccess('/vendor/uploads');

  return (
    <>
      <PageHeader
        title="My submissions"
        breadcrumbs={[{ label: 'Submissions' }, { label: 'My submissions' }]}
        description="Files your organisation has sent, and the validation result for each. Rejected rows list the original file row number so they can be corrected at source."
      />
      <div className="px-4 pt-4">
        <Callout tone="info">
          Submissions are visible to the commissioning company&apos;s data stewards. Analytical
          results derived from this data are not shared back through this portal.
        </Callout>
      </div>
      <UploadsWorkspace vendorScoped />
    </>
  );
}
