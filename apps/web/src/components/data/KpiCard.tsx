'use client';

import * as React from 'react';
import { ArrowDownRight, ArrowRight, ArrowUpRight } from 'lucide-react';

import type { Kpi } from '@/lib/api/types';
import { EvidenceStatus } from '@/lib/api/enums';
import { cn } from '@/lib/utils';
import {
  EM_DASH,
  formatCompact,
  formatCurrency,
  formatCurrencyCompact,
  formatDecimal,
  formatInteger,
  formatMultiple,
  formatPercent,
  formatSignedPercent,
} from '@/lib/formatters';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { EvidenceBadge } from './EvidenceBadge';
import { LineageChip } from './LineageChip';
import { MetricTooltip } from './MetricTooltip';

/**
 * A single headline figure.
 *
 * Four rules this component enforces so no dashboard has to remember them:
 *
 *  1. An estimate is shown with its interval, or not at all. A causal number
 *     without a range reads as a measurement, which it is not.
 *  2. `NOT_RELIABLY_ESTIMABLE` renders the refusal, never a zero (F-9).
 *  3. Direction of change is an arrow *and* a word, never colour alone.
 *  4. "Good" depends on the metric: spend falling is good, reach falling is not.
 *     `higherIsBetter` comes from the payload, so the card never guesses.
 */

export interface KpiCardProps {
  kpi?: Kpi | null;
  loading?: boolean;
  /** Sparkline or any small visual; rendered right of the value. */
  trendSlot?: React.ReactNode;
  /** ISO-4217 from the active tenant, for CURRENCY units. */
  currency?: string;
  compact?: boolean;
  className?: string;
  onClick?: () => void;
}

function formatValue(value: number, unit: Kpi['unit'], currency: string, compact: boolean): string {
  switch (unit) {
    case 'CURRENCY':
      return compact ? formatCurrencyCompact(value, { currency }) : formatCurrency(value, { currency });
    case 'PERCENT':
      return formatPercent(value);
    case 'MULTIPLE':
      return formatMultiple(value);
    case 'RATIO':
      return formatDecimal(value, 2);
    case 'RX':
    case 'COUNT':
      return compact ? formatCompact(value) : formatInteger(value);
    default:
      return formatDecimal(value);
  }
}

export function KpiCard({
  kpi,
  loading = false,
  trendSlot,
  currency = 'USD',
  compact = false,
  className,
  onClick,
}: KpiCardProps) {
  if (loading || !kpi) {
    return (
      <Card className={cn('flex flex-col gap-3 p-4', className)}>
        <Skeleton className="h-3 w-24" label="Loading metric" />
        <Skeleton className="h-7 w-32" />
        <Skeleton className="h-3 w-40" />
      </Card>
    );
  }

  const notEstimable = kpi.evidence?.status === EvidenceStatus.NOT_RELIABLY_ESTIMABLE;
  const hasValue = typeof kpi.value === 'number' && !notEstimable;

  const change = kpi.changeRatio;
  const direction = change == null ? 'flat' : change > 0.0005 ? 'up' : change < -0.0005 ? 'down' : 'flat';
  const good =
    direction === 'flat' ? null : kpi.higherIsBetter ? direction === 'up' : direction === 'down';

  const DirectionIcon = direction === 'up' ? ArrowUpRight : direction === 'down' ? ArrowDownRight : ArrowRight;

  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-text-muted">
          <MetricTooltip metric={kpi.key} definition={kpi.definition} label={kpi.label}>
            {kpi.label}
          </MetricTooltip>
        </p>
        {kpi.evidence ? <EvidenceBadge grade={kpi.evidence.grade} /> : null}
      </div>

      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0">
          {hasValue ? (
            <p className="truncate text-display font-semibold leading-none tracking-tight text-text">
              {formatValue(kpi.value as number, kpi.unit, currency, compact)}
            </p>
          ) : (
            <p className="text-sm font-semibold leading-tight text-warning">Not reliably estimable</p>
          )}

          {hasValue && kpi.interval ? (
            <p className="mt-1 font-mono text-2xs text-text-subtle">
              {/* A missing bound renders as an em dash, not as the point estimate:
                  a one-sided interval must not read as a tight one. */}
              {kpi.interval.lower == null
                ? EM_DASH
                : formatValue(kpi.interval.lower, kpi.unit, currency, true)}
              {' – '}
              {kpi.interval.upper == null
                ? EM_DASH
                : formatValue(kpi.interval.upper, kpi.unit, currency, true)}
              <span className="ml-1 font-sans">
                {kpi.interval.confidenceLevel
                  ? `${formatPercent(kpi.interval.confidenceLevel, 0)} interval`
                  : 'interval'}
              </span>
            </p>
          ) : null}
        </div>

        {trendSlot ? <div className="shrink-0">{trendSlot}</div> : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {hasValue && change != null ? (
          <span
            className={cn(
              'inline-flex items-center gap-1 text-xs font-medium',
              good === null ? 'text-text-muted' : good ? 'text-positive' : 'text-danger',
            )}
          >
            <DirectionIcon aria-hidden="true" className="size-3.5" />
            {formatSignedPercent(change)}
            {/* The arrow and the sign carry the direction; the word carries the
                judgement, so a reader who cannot distinguish the hues still
                learns whether the movement is good. */}
            <span className="sr-only">
              {good === null ? 'unchanged' : good ? 'favourable movement' : 'unfavourable movement'}
            </span>
          </span>
        ) : null}
        {kpi.comparisonLabel ? (
          <span className="text-xs text-text-subtle">{kpi.comparisonLabel}</span>
        ) : null}
        {!hasValue && kpi.evidence?.reason ? (
          <span className="text-xs text-text-muted">{kpi.evidence.reason}</span>
        ) : null}
      </div>

      {kpi.lineage ? <LineageChip lineage={kpi.lineage} compact className="mt-1 self-start" /> : null}
    </>
  );

  if (onClick) {
    return (
      <Card className={cn('transition-colors hover:border-border-strong', className)}>
        <button
          type="button"
          onClick={onClick}
          className="flex w-full flex-col gap-2 p-4 text-left"
        >
          {body}
        </button>
      </Card>
    );
  }

  return <Card className={cn('flex flex-col gap-2 p-4', className)}>{body}</Card>;
}

/** Placeholder used while a KPI row is loading, so the grid does not jump. */
export function KpiCardSkeleton({ className }: { className?: string }) {
  return <KpiCard loading className={className} />;
}

export { EM_DASH };
