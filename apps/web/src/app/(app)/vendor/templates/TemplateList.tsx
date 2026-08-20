'use client';

import { FileSpreadsheet, FileText } from 'lucide-react';

import { useSession } from '@/lib/api/queries/session';
import { useUploadTemplates } from '@/lib/api/queries/uploads';
import { EmptyState, ErrorState } from '@/components/data/states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { formatBytes, formatInteger } from '@/lib/formatters';

/**
 * The file specifications a vendor may submit against.
 *
 * Version is shown on every card and is not decorative: a batch is validated
 * against the template version that was current when the session was created, so
 * a vendor working from last quarter's spreadsheet needs to see, at a glance,
 * that the spec has moved.
 */
export function TemplateList() {
  const { data: session } = useSession();
  const tenantId = session?.activeTenant?.tenantId ?? null;
  const templates = useUploadTemplates(tenantId);

  if (templates.isPending) {
    return (
      <div className="grid gap-3 p-4 lg:grid-cols-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-44 w-full" label={i === 0 ? 'Loading templates' : undefined} />
        ))}
      </div>
    );
  }

  if (templates.isError) {
    return (
      <div className="p-4">
        <ErrorState error={templates.error} onRetry={() => void templates.refetch()} />
      </div>
    );
  }

  const items = templates.data?.items ?? [];
  if (items.length === 0) {
    return (
      <div className="p-4">
        <EmptyState
          title="No templates published"
          description="The commissioning company has not published any file specifications yet. You will be notified when one is available."
        />
      </div>
    );
  }

  return (
    <div className="grid gap-3 p-4 lg:grid-cols-2">
      {items.map((template) => (
        <Card key={`${template.datasetType}-${template.templateVersion}`}>
          <CardHeader bordered className="flex-row items-start justify-between gap-3">
            <div className="min-w-0">
              <CardTitle>{template.label}</CardTitle>
              <p className="mt-1 text-xs leading-relaxed text-text-muted">{template.description}</p>
            </div>
            <Badge variant="outline" className="shrink-0 font-mono">
              v{template.templateVersion}
            </Badge>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <dl className="grid grid-cols-3 gap-3 text-xs">
              <Spec label="Formats">{template.acceptedFormats.join(', ')}</Spec>
              <Spec label="Max size">{formatBytes(template.maxBytes)}</Spec>
              <Spec label="Max rows">{formatInteger(template.maxRows)}</Spec>
            </dl>
            <div className="flex flex-wrap gap-2">
              <Button asChild size="sm" variant="secondary" iconLeft={<FileSpreadsheet />}>
                {/* A real anchor with `download`: the template is served from
                    object storage behind a signed URL, and routing it through the
                    client router would strip the redirect. */}
                <a href={template.downloadUrl} download>
                  Download template
                </a>
              </Button>
              {template.dataDictionaryUrl ? (
                <Button asChild size="sm" variant="ghost" iconLeft={<FileText />}>
                  <a href={template.dataDictionaryUrl} target="_blank" rel="noopener noreferrer">
                    Data dictionary
                  </a>
                </Button>
              ) : null}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function Spec({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-2xs uppercase tracking-wide text-text-subtle">{label}</dt>
      <dd className="truncate font-medium text-text">{children}</dd>
    </div>
  );
}
