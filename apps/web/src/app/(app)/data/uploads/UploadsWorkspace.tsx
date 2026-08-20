'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';

import type { UploadBatch } from '@/lib/api/types';
import { useSession } from '@/lib/api/queries/session';
import { useUploadHistory, useUploadTemplates } from '@/lib/api/queries/uploads';
import { UploadDropzone, UploadResult } from '@/components/data/UploadDropzone';
import { DataTable } from '@/components/data/DataTable';
import { StatusBadge } from '@/components/data/StatusBadge';
import { EmptyState, ErrorState } from '@/components/data/states';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EM_DASH, formatBytes, formatDateTime, formatInteger } from '@/lib/formatters';
import { humanizeEnum } from '@/lib/utils';

/**
 * Upload workspace: submit a batch, then watch it through validation.
 *
 * The submitted batch is kept on screen after it completes rather than being
 * folded straight into the history table. The moment a user has just sent
 * something is exactly the moment they need the row counts and the issue list;
 * making them find their own submission in a list of forty is a small cruelty
 * that produces duplicate uploads.
 */
export function UploadsWorkspace({ vendorScoped = false }: { vendorScoped?: boolean }) {
  const { data: session } = useSession();
  const tenantId = session?.activeTenant?.tenantId ?? null;

  const templates = useUploadTemplates(tenantId);
  const history = useUploadHistory(tenantId, {});
  const [completed, setCompleted] = React.useState<UploadBatch | null>(null);

  const columns = React.useMemo<Array<ColumnDef<UploadBatch, unknown>>>(
    () => [
      {
        id: 'fileName',
        header: 'File',
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col">
            <span className="truncate font-medium text-text">{row.original.fileName}</span>
            <span className="text-2xs text-text-subtle">
              {humanizeEnum(row.original.datasetType)} · {formatBytes(row.original.sizeBytes)}
            </span>
          </span>
        ),
      },
      {
        id: 'status',
        header: 'Status',
        cell: ({ row }) => <StatusBadge value={row.original.status} />,
      },
      {
        id: 'accepted',
        header: 'Accepted',
        // `numeric` right-aligns and switches the cell to tabular figures, which
        // is what makes a column of counts scannable.
        meta: { numeric: true },
        cell: ({ row }) => formatInteger(row.original.acceptedRowCount),
      },
      {
        id: 'rejected',
        header: 'Rejected',
        meta: { numeric: true },
        cell: ({ row }) => formatInteger(row.original.rejectedRowCount),
      },
      {
        id: 'submitted',
        header: 'Submitted',
        cell: ({ row }) => formatDateTime(row.original.submittedAt),
      },
      {
        id: 'submittedBy',
        header: 'By',
        cell: ({ row }) => row.original.submittedByName ?? EM_DASH,
      },
    ],
    [],
  );

  return (
    <div className="flex flex-col gap-4 p-4">
      <UploadDropzone
        templates={templates.data?.items ?? []}
        tenantId={tenantId}
        onCompleted={setCompleted}
      />

      {completed ? <UploadResult batch={completed} /> : null}

      <Card>
        <CardHeader bordered>
          <CardTitle>{vendorScoped ? 'Your submissions' : 'Recent batches'}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {history.isError ? (
            <ErrorState error={history.error} onRetry={() => void history.refetch()} compact />
          ) : (
            <DataTable
              columns={columns}
              data={history.data?.items ?? []}
              loading={history.isPending}
              getRowId={(row) => row.uploadId}
              emptyTitle="No submissions yet"
              emptyDescription={
                vendorScoped
                  ? 'Files your organisation submits will appear here with their validation results.'
                  : 'Batches submitted by your team and by contributing vendors appear here.'
              }
            />
          )}
        </CardContent>
      </Card>

      {templates.isSuccess && templates.data.items.length === 0 ? (
        <EmptyState
          compact
          title="No dataset templates are published"
          description="An administrator must publish at least one file specification before submissions can be accepted."
        />
      ) : null}
    </div>
  );
}
