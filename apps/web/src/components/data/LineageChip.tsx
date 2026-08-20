'use client';

import { GitBranch } from 'lucide-react';

import type { Lineage } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { formatDateTime } from '@/lib/formatters';
import { CopyButton } from '@/components/ui/copy-button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { StatusBadge } from './StatusBadge';

/**
 * The provenance tuple, plan.md §14.
 *
 * Every number this product shows is reproducible from
 * `tenant · data_version · run_id · model_version · finance_version`. A figure
 * without its lineage is not auditable, so this chip accompanies any surface
 * that reports an estimate — and it must be copyable in one click, because the
 * first thing a reviewer does with a disputed number is paste the tuple into a
 * ticket.
 */

export interface LineageChipProps {
  lineage: Lineage | null | undefined;
  className?: string;
  /** Renders only the data version inline; full tuple stays in the popover. */
  compact?: boolean;
}

function tupleString(lineage: Lineage): string {
  return [
    lineage.tenantId,
    lineage.dataVersion,
    lineage.runId,
    lineage.modelVersion,
    lineage.financeVersion,
  ]
    .map((part) => part ?? '—')
    .join(' · ');
}

const FIELDS: ReadonlyArray<{ key: keyof Lineage; label: string }> = [
  { key: 'tenantId', label: 'Tenant' },
  { key: 'dataVersion', label: 'Data version' },
  { key: 'runId', label: 'Run' },
  { key: 'modelVersion', label: 'Model version' },
  { key: 'financeVersion', label: 'Finance version' },
];

export function LineageChip({ lineage, className, compact }: LineageChipProps) {
  if (!lineage) return null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex max-w-full items-center gap-1.5 rounded-sm border border-border bg-surface px-1.5 py-0.5',
            'font-mono text-2xs text-text-muted transition-colors hover:border-border-strong hover:text-text',
            className,
          )}
          aria-label="Show data lineage"
        >
          <GitBranch aria-hidden="true" className="size-3 shrink-0" />
          <span className="truncate">
            {compact ? (lineage.dataVersion ?? 'no data version') : tupleString(lineage)}
          </span>
        </button>
      </PopoverTrigger>

      <PopoverContent className="w-80">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-sm font-semibold text-text">Lineage</p>
            <p className="text-xs text-text-muted">Everything needed to reproduce this figure.</p>
          </div>
          <CopyButton value={tupleString(lineage)} label="Copy lineage tuple" />
        </div>

        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
          {FIELDS.map(({ key, label }) => {
            const value = lineage[key];
            return (
              <div key={key} className="contents">
                <dt className="text-text-subtle">{label}</dt>
                <dd className="truncate font-mono text-text" title={String(value ?? '')}>
                  {typeof value === 'string' && value ? value : '—'}
                </dd>
              </div>
            );
          })}
          <dt className="text-text-subtle">Computed</dt>
          <dd className="text-text">{formatDateTime(lineage.computedAt)}</dd>
        </dl>

        {lineage.publicationState ? (
          <div className="mt-3 border-t border-border pt-3">
            <StatusBadge value={lineage.publicationState} />
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
