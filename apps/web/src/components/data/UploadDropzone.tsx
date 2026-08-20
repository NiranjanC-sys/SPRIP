'use client';

import * as React from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Info,
  UploadCloud,
  X,
} from 'lucide-react';

import { IssueSeverity, UploadStatus, type DatasetType } from '@/lib/api/enums';
import type { UploadBatch, UploadTemplate } from '@/lib/api/types';
import { toDisplayMessage } from '@/lib/api/errors';
import { cn, humanizeEnum } from '@/lib/utils';
import { formatBytes, formatInteger, formatPercent } from '@/lib/formatters';
import {
  useConfirmUpload,
  useCreateUploadSession,
  useUploadBatch,
  type CreateUploadSessionInput,
} from '@/lib/api/queries/uploads';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { CopyButton } from '@/components/ui/copy-button';
import { IconButton } from '@/components/ui/icon-button';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { StatusBadge } from './StatusBadge';

/**
 * The ingestion front door (plan.md §10.3).
 *
 * The one thing this component exists to get right is that **transfer progress
 * and processing progress are different numbers**. A 400MB claims extract can
 * finish uploading in twelve seconds and then spend four minutes in validation.
 * A single merged bar sits at 100% for four minutes, at which point every user
 * concludes the product has hung and clicks the button again. So there are two
 * bars, they are labelled differently, and the second one only appears once the
 * bytes have actually landed.
 *
 * The flow is the six-step one from the plan: request a session → PUT the bytes
 * straight to object storage → confirm → poll the batch → show the receipt and
 * the validation summary → offer the error report.
 */

type Phase = 'idle' | 'requesting' | 'transferring' | 'confirming' | 'processing' | 'done' | 'failed';

export interface UploadDropzoneProps {
  templates: readonly UploadTemplate[];
  tenantId: string | null;
  /** Pre-selects and locks the dataset type — used on dataset-specific pages. */
  datasetType?: DatasetType;
  /** Scope the batch to a brand / campaign / event when the page implies one. */
  scope?: Pick<CreateUploadSessionInput, 'brandId' | 'campaignId' | 'eventId'>;
  onCompleted?: (batch: UploadBatch) => void;
  className?: string;
}

export function UploadDropzone({
  templates,
  tenantId,
  datasetType,
  scope,
  onCompleted,
  className,
}: UploadDropzoneProps) {
  const [selectedType, setSelectedType] = React.useState<string>(
    datasetType ?? templates[0]?.datasetType ?? '',
  );
  const [file, setFile] = React.useState<File | null>(null);
  const [phase, setPhase] = React.useState<Phase>('idle');
  const [transferRatio, setTransferRatio] = React.useState(0);
  const [uploadId, setUploadId] = React.useState<string | null>(null);
  const [failure, setFailure] = React.useState<string | null>(null);
  const [dragging, setDragging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const xhrRef = React.useRef<XMLHttpRequest | null>(null);

  const createSession = useCreateUploadSession();
  const confirmUpload = useConfirmUpload(tenantId);
  const batchQuery = useUploadBatch(tenantId, phase === 'processing' || phase === 'done' ? uploadId : null);
  const batch = batchQuery.data ?? null;

  const template = React.useMemo(
    () => templates.find((t) => t.datasetType === selectedType) ?? null,
    [templates, selectedType],
  );

  // Once the server reaches a terminal state, stop calling this "processing" so
  // the summary and the receipt take over the panel.
  React.useEffect(() => {
    if (!batch || phase !== 'processing') return;
    if (batch.processingProgress === 1 || batch.completedAt) {
      setPhase('done');
      onCompleted?.(batch);
    }
  }, [batch, phase, onCompleted]);

  React.useEffect(() => () => xhrRef.current?.abort(), []);

  const reset = () => {
    xhrRef.current?.abort();
    xhrRef.current = null;
    setFile(null);
    setPhase('idle');
    setTransferRatio(0);
    setUploadId(null);
    setFailure(null);
  };

  const validateLocally = (candidate: File): string | null => {
    if (!template) return 'Choose a dataset type first.';
    if (candidate.size > template.maxBytes) {
      return `That file is ${formatBytes(candidate.size)}; the limit for ${template.label} is ${formatBytes(template.maxBytes)}. Split it and upload the parts.`;
    }
    const extension = candidate.name.split('.').pop()?.toUpperCase() ?? '';
    const accepted = template.acceptedFormats.map((f) => f.toUpperCase());
    // Checking here saves a round trip and, more usefully, gives an error that
    // names the accepted formats instead of a generic 415 from the worker.
    if (extension && accepted.length > 0 && !accepted.includes(extension === 'XLS' ? 'XLSX' : extension)) {
      return `${template.label} accepts ${accepted.join(', ')}. This file looks like .${extension.toLowerCase()}.`;
    }
    return null;
  };

  const pickFile = (candidate: File | undefined) => {
    if (!candidate) return;
    const problem = validateLocally(candidate);
    setFailure(problem);
    setFile(problem ? null : candidate);
    setPhase('idle');
    setTransferRatio(0);
    setUploadId(null);
  };

  /** Steps 4–7 of §10.3. */
  const start = async () => {
    if (!file || !template) return;
    setFailure(null);
    setPhase('requesting');

    try {
      const session = await createSession.mutateAsync({
        datasetType: template.datasetType,
        fileName: file.name,
        sizeBytes: file.size,
        contentType: file.type || 'application/octet-stream',
        ...scope,
      });

      setUploadId(session.uploadId);
      setPhase('transferring');

      // XHR rather than fetch: `fetch` still has no upload progress event, and a
      // progress bar that cannot report progress is decoration.
      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhrRef.current = xhr;
        xhr.open(session.method, session.uploadUrl, true);
        for (const [header, value] of Object.entries(session.headers)) {
          xhr.setRequestHeader(header, value);
        }
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) setTransferRatio(event.loaded / event.total);
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) resolve();
          else reject(new Error(`Storage rejected the transfer (HTTP ${xhr.status}).`));
        };
        xhr.onerror = () => reject(new Error('The network dropped during transfer.'));
        xhr.onabort = () => reject(new Error('Transfer cancelled.'));
        xhr.send(file);
      });

      setTransferRatio(1);
      setPhase('confirming');
      await confirmUpload.mutateAsync(session.uploadId);
      setPhase('processing');
    } catch (error) {
      setFailure(toDisplayMessage(error));
      setPhase('failed');
    }
  };

  const busy = phase === 'requesting' || phase === 'transferring' || phase === 'confirming';
  const showProcessing = phase === 'processing' || phase === 'done';

  return (
    <div className={cn('flex flex-col gap-4', className)}>
      <Card>
        <CardHeader bordered>
          <CardTitle>Upload a file</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {!datasetType ? (
            <label className="flex max-w-md flex-col gap-1.5">
              <span className="text-xs font-medium text-text-muted">Dataset</span>
              <Select value={selectedType} onValueChange={setSelectedType} disabled={busy || showProcessing}>
                <SelectTrigger>
                  <SelectValue placeholder="Choose a dataset" />
                </SelectTrigger>
                <SelectContent>
                  {templates.map((t) => (
                    <SelectItem key={t.datasetType} value={t.datasetType}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
          ) : null}

          {template ? (
            <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
              <span>{template.description}</span>
              <Badge variant="outline">v{template.templateVersion}</Badge>
              <Button asChild variant="link" size="sm" iconLeft={<Download />}>
                <a href={template.downloadUrl} download>
                  Template
                </a>
              </Button>
              {template.dataDictionaryUrl ? (
                <Button asChild variant="link" size="sm">
                  <a href={template.dataDictionaryUrl}>Data dictionary</a>
                </Button>
              ) : null}
              <span className="text-text-subtle">
                Max {formatBytes(template.maxBytes)} · {formatInteger(template.maxRows)} rows ·{' '}
                {template.acceptedFormats.join(', ')}
              </span>
            </div>
          ) : null}

          {/* The drop target is also a button, so keyboard users are not asked to
              drag anything. */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              pickFile(e.dataTransfer.files[0]);
            }}
            className={cn(
              'flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors',
              dragging ? 'border-primary bg-primary/5' : 'border-border bg-surface-sunken',
              (busy || showProcessing) && 'pointer-events-none opacity-60',
            )}
          >
            <UploadCloud aria-hidden="true" className="size-7 text-text-subtle" />
            <p className="text-sm text-text">
              Drag a file here, or{' '}
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="rounded-sm font-medium text-primary underline underline-offset-4"
              >
                browse
              </button>
            </p>
            <p className="text-xs text-text-subtle">
              Nothing is ingested until you review the validation summary.
            </p>
            <input
              ref={inputRef}
              type="file"
              className="sr-only"
              accept={template?.acceptedFormats.map((f) => `.${f.toLowerCase()}`).join(',')}
              onChange={(e) => pickFile(e.target.files?.[0])}
            />
          </div>

          {file ? (
            <div className="flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-2">
              <FileSpreadsheet aria-hidden="true" className="size-4 shrink-0 text-text-subtle" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-text">{file.name}</p>
                <p className="text-xs text-text-subtle">{formatBytes(file.size)}</p>
              </div>
              {phase === 'idle' ? (
                <IconButton label="Remove file" variant="ghost" size="sm" onClick={reset}>
                  <X />
                </IconButton>
              ) : null}
            </div>
          ) : null}

          {failure ? (
            <Alert tone="danger" title="Upload could not continue">
              {failure}
            </Alert>
          ) : null}

          {/* Two bars, never one. See the note at the top of this file. */}
          {phase !== 'idle' && phase !== 'failed' ? (
            <div className="flex flex-col gap-3">
              <ProgressRow
                label="File transfer"
                value={phase === 'requesting' ? null : transferRatio}
                tone={transferRatio === 1 ? 'positive' : 'primary'}
                hint={
                  phase === 'requesting'
                    ? 'Requesting a destination…'
                    : transferRatio < 1
                      ? 'Sending bytes to secure storage'
                      : 'Bytes received'
                }
              />
              {showProcessing || phase === 'confirming' ? (
                <ProgressRow
                  label="Server-side validation"
                  value={batch?.processingProgress ?? null}
                  tone={batch?.status === UploadStatus.FAILED ? 'danger' : 'primary'}
                  hint={
                    batch
                      ? `Parsing, validating and conforming rows · ${humanizeEnum(batch.status)}`
                      : 'Queued for processing'
                  }
                />
              ) : null}
            </div>
          ) : null}

          <div className="flex items-center gap-2">
            <Button
              onClick={start}
              disabled={!file || !template || busy || showProcessing}
              loading={busy}
              loadingLabel={phase === 'transferring' ? 'Uploading…' : 'Preparing…'}
              iconLeft={<UploadCloud />}
            >
              Start upload
            </Button>
            {phase !== 'idle' ? (
              <Button variant="ghost" onClick={reset}>
                {showProcessing ? 'Upload another' : 'Cancel'}
              </Button>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {batch ? <UploadResult batch={batch} /> : null}
    </div>
  );
}

/**
 * A progress bar with a visible caption. The `<Progress>` primitive carries only
 * the accessible name; the caption is what tells a waiting user *which* of the
 * two phases they are in, which is the entire point of splitting them.
 */
function ProgressRow({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: number | null;
  hint: string;
  tone: 'primary' | 'positive' | 'danger';
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-text">{label}</span>
        <span className="font-mono text-2xs text-text-muted" aria-hidden="true">
          {value === null ? '—' : formatPercent(value, 0)}
        </span>
      </div>
      <Progress label={label} value={value} tone={tone} />
      <p className="text-2xs text-text-subtle">{hint}</p>
    </div>
  );
}

/* --- receipt + validation summary ----------------------------------------- */

const SEVERITY_TONE: Readonly<Record<string, 'danger' | 'warning' | 'neutral'>> = {
  [IssueSeverity.ERROR]: 'danger',
  [IssueSeverity.WARNING]: 'warning',
  [IssueSeverity.INFO]: 'neutral',
};

export function UploadResult({ batch }: { batch: UploadBatch }) {
  const errorCount = batch.issues.filter((i) => i.severity === IssueSeverity.ERROR).length;
  const settled = Boolean(batch.completedAt);

  return (
    <Card>
      <CardHeader bordered className="flex-row items-center justify-between gap-2">
        <CardTitle>Result</CardTitle>
        <StatusBadge value={batch.status} />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Figure label="Rows read" value={batch.rowsTotal} />
          <Figure label="Accepted" value={batch.rowsAccepted} tone="positive" />
          <Figure label="Rejected" value={batch.rowsRejected} tone="danger" />
          <Figure label="Quarantined" value={batch.rowsQuarantined} tone="warning" />
        </dl>

        {settled && errorCount === 0 ? (
          <Alert tone="positive" title="Accepted">
            Every row passed validation. The batch is staged against the next data version.
          </Alert>
        ) : null}

        {batch.issues.length > 0 ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-text">Validation issues</p>
              {batch.errorReportUrl ? (
                <Button asChild size="sm" variant="secondary" iconLeft={<Download />}>
                  <a href={batch.errorReportUrl} download>
                    Download full error report
                  </a>
                </Button>
              ) : null}
            </div>
            {/* Row numbers are the file's own, not the parser's — the person
                fixing this is looking at a spreadsheet, not our chunk offsets. */}
            <div className="scroll-thin max-h-72 overflow-auto rounded-md border border-border">
              <Table>
                <TableHeader sticky>
                  <TableRow>
                    <TableHead density="compact">Severity</TableHead>
                    <TableHead density="compact">Row</TableHead>
                    <TableHead density="compact">Column</TableHead>
                    <TableHead density="compact">Issue</TableHead>
                    <TableHead density="compact" numeric>
                      Count
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {batch.issues.map((issue, index) => (
                    <TableRow key={`${issue.code}-${issue.rowNumber ?? 'x'}-${index}`}>
                      <TableCell density="compact">
                        <Badge variant={SEVERITY_TONE[issue.severity] ?? 'neutral'} size="sm">
                          {issue.severity === IssueSeverity.ERROR ? (
                            <AlertTriangle aria-hidden="true" />
                          ) : issue.severity === IssueSeverity.WARNING ? (
                            <AlertTriangle aria-hidden="true" />
                          ) : (
                            <Info aria-hidden="true" />
                          )}
                          {issue.severity}
                        </Badge>
                      </TableCell>
                      <TableCell density="compact" numeric>
                        {issue.rowNumber ?? '—'}
                      </TableCell>
                      <TableCell density="compact">
                        <code className="font-mono text-2xs">{issue.column ?? '—'}</code>
                      </TableCell>
                      <TableCell density="compact">
                        <span className="text-text">{issue.message}</span>
                        <code className="ml-1.5 font-mono text-2xs text-text-subtle">{issue.code}</code>
                      </TableCell>
                      <TableCell density="compact" numeric>
                        {formatInteger(issue.occurrences)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        ) : null}

        {batch.receipt ? (
          <div className="rounded-md border border-border bg-surface-sunken p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="flex items-center gap-1.5 text-sm font-medium text-text">
                <CheckCircle2 aria-hidden="true" className="size-4 text-positive" />
                Object receipt
              </p>
              <CopyButton value={batch.receipt.checksumSha256} label="Copy checksum" size="sm" />
            </div>
            {/* plan.md §21.7 — the checksum is what makes "we ingested exactly the
                file you sent" a provable claim rather than an assurance. */}
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-text-subtle">Bucket</dt>
              <dd className="truncate font-mono text-text">{batch.receipt.bucket}</dd>
              <dt className="text-text-subtle">Key</dt>
              <dd className="truncate font-mono text-text">{batch.receipt.objectKey}</dd>
              <dt className="text-text-subtle">SHA-256</dt>
              <dd className="truncate font-mono text-text">{batch.receipt.checksumSha256}</dd>
              <dt className="text-text-subtle">Size</dt>
              <dd className="text-text">{formatBytes(batch.receipt.sizeBytes)}</dd>
            </dl>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Figure({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: number | null;
  tone?: 'neutral' | 'positive' | 'warning' | 'danger';
}) {
  const toneClass =
    tone === 'positive'
      ? 'text-positive'
      : tone === 'danger'
        ? 'text-danger'
        : tone === 'warning'
          ? 'text-warning'
          : 'text-text';
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-2xs uppercase tracking-wide text-text-subtle">{label}</dt>
      <dd className={cn('font-mono text-lg font-semibold tabular-nums', value == null ? 'text-text-subtle' : toneClass)}>
        {value == null ? '—' : formatInteger(value)}
      </dd>
    </div>
  );
}
