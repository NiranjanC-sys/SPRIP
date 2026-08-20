'use client';

import Link from 'next/link';
import { AlertTriangle, CircleCheck, CircleHelp, Clock } from 'lucide-react';

import type { Freshness } from '@/lib/api/types';
import { DataVersionStatus } from '@/lib/api/enums';
import { formatDateTime, formatInteger, formatRelativeTime } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusBadge } from '@/components/data/StatusBadge';

/**
 * "How old is what I am looking at."
 *
 * This sits in the top bar of every page because the question it answers is the
 * one that invalidates a screenshot. A number from a data version published
 * eleven days ago, taken into a Monday brand meeting as current, is the exact
 * failure the whole lineage story exists to prevent — so the answer is always on
 * screen, not one click away.
 *
 * Three states, and the amber one is deliberately loud: any stale source or
 * failed job downgrades the indicator even when the published version itself is
 * fine, because "the version is current but three feeds did not arrive" is not a
 * green state.
 */

export interface FreshnessIndicatorProps {
  freshness: Freshness | undefined;
  loading?: boolean;
  className?: string;
}

type Tone = 'positive' | 'warning' | 'danger' | 'neutral';

function toneOf(freshness: Freshness): Tone {
  if (freshness.failedJobCount > 0) return 'danger';
  if (freshness.staleSourceCount > 0) return 'warning';
  if (freshness.dataVersionStatus === DataVersionStatus.PUBLISHED) return 'positive';
  return 'neutral';
}

const TONE_CLASS: Readonly<Record<Tone, string>> = {
  positive: 'text-positive',
  warning: 'text-warning',
  danger: 'text-danger',
  neutral: 'text-text-subtle',
};

export function FreshnessIndicator({ freshness, loading, className }: FreshnessIndicatorProps) {
  if (loading || !freshness) {
    return <Skeleton className={cn('h-6 w-28', className)} label="Loading data freshness" />;
  }

  const tone = toneOf(freshness);
  const Icon =
    tone === 'positive'
      ? CircleCheck
      : tone === 'neutral'
        ? CircleHelp
        : tone === 'danger'
          ? AlertTriangle
          : Clock;

  const relative = freshness.dataVersionPublishedAt
    ? formatRelativeTime(freshness.dataVersionPublishedAt)
    : 'No published version';

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'flex items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1 text-xs text-text-muted hover:border-border-strong',
            className,
          )}
        >
          <Icon aria-hidden="true" className={cn('size-3.5', TONE_CLASS[tone])} />
          <span className="hidden sm:inline">Data</span>
          <span className="font-medium text-text">{relative}</span>
        </button>
      </PopoverTrigger>

      <PopoverContent align="end" className="w-80">
        <p className="text-sm font-semibold text-text">Data freshness</p>
        <dl className="mt-2 grid grid-cols-[auto_1fr] items-baseline gap-x-3 gap-y-1.5 text-xs">
          <dt className="text-text-subtle">Version</dt>
          <dd className="truncate font-mono text-text">{freshness.dataVersion ?? '—'}</dd>

          <dt className="text-text-subtle">State</dt>
          <dd>
            {freshness.dataVersionStatus ? (
              <StatusBadge value={freshness.dataVersionStatus} />
            ) : (
              <span className="text-text-muted">Unknown</span>
            )}
          </dd>

          <dt className="text-text-subtle">Published</dt>
          <dd className="text-text">
            {freshness.dataVersionPublishedAt ? formatDateTime(freshness.dataVersionPublishedAt) : '—'}
          </dd>

          {freshness.lastSuccessfulRunAt ? (
            <>
              <dt className="text-text-subtle">Last run</dt>
              <dd className="text-text">{formatDateTime(freshness.lastSuccessfulRunAt)}</dd>
            </>
          ) : null}

          <dt className="text-text-subtle">Stale feeds</dt>
          <dd className={freshness.staleSourceCount > 0 ? 'font-medium text-warning' : 'text-text'}>
            {formatInteger(freshness.staleSourceCount)}
          </dd>

          <dt className="text-text-subtle">Failed jobs</dt>
          <dd className={freshness.failedJobCount > 0 ? 'font-medium text-danger' : 'text-text'}>
            {formatInteger(freshness.failedJobCount)}
          </dd>
        </dl>

        {tone !== 'positive' ? (
          <p className="mt-3 rounded-sm bg-surface-sunken p-2 text-xs leading-relaxed text-text-muted">
            Figures on this page resolve to the version above. Treat them as provisional until the
            outstanding feeds land.
          </p>
        ) : null}

        <Link
          href="/data-health"
          className="mt-3 inline-block text-xs font-medium text-primary underline underline-offset-4"
        >
          Open data &amp; model health
        </Link>
      </PopoverContent>
    </Popover>
  );
}
