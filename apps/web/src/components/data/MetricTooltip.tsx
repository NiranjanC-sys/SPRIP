'use client';

import * as React from 'react';
import { Info } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Tooltip } from '@/components/ui/tooltip';

/**
 * Shared metric definitions.
 *
 * These are the words people argue about in a review meeting. Keeping them in
 * one file — rather than in each dashboard's copy — is what stops "net ROI" from
 * meaning two different things on two pages. When the API starts returning
 * tenant-specific definitions, `definition` on the Kpi payload overrides these.
 */

export const METRIC_DEFINITIONS: Readonly<Record<string, string>> = {
  nrx: 'New prescriptions (NRx): scripts written for a patient not previously on the product in the lookback window. The primary outcome for speaker-programme impact, because it responds faster than total volume.',
  trx: 'Total prescriptions (TRx): new plus refill volume. Slower moving than NRx and more sensitive to persistence, so it is reported as a secondary outcome.',
  lift:
    'Incremental lift: the difference between the attendee cohort and its matched control over the post-event window, attributable to attendance. It is an estimate with an interval, never a single certain number.',
  incremental_nrx:
    'Incremental NRx: the estimated number of new prescriptions that would not have occurred without the programme, after matching attendees to comparable non-attendees.',
  bcr: 'Benefit-cost ratio (BCR): gross financial benefit divided by fully loaded programme cost. A BCR of 1.0 means the programme paid for itself exactly.',
  net_roi:
    'Net ROI: (benefit − fully loaded cost) ÷ fully loaded cost. Reported alongside its interval; a point estimate on its own overstates precision.',
  fully_loaded_spend:
    'Fully loaded spend: direct event cost plus allocated speaker fees, travel, venue, agency and internal time — the cost the finance team recognises, not just the invoice.',
  verified_reach:
    'Verified reach: distinct HCPs whose attendance is evidenced by a badge scan, sign-in sheet or platform log. Vendor attestation alone does not count as verified.',
  estimable_share:
    'Share of events for which the evidence gates were met and a causal estimate could be produced. A low share means the analysis is thin, not that the programme failed.',
  interval:
    'The bracketed range is the confidence interval at the stated level. Two estimates whose intervals overlap should not be described as different.',
  control_cohort:
    'The comparison group. Invited non-attendees are the strongest available control; a propensity-matched general cohort is weaker and caps the achievable evidence grade.',
};

export type MetricKey = keyof typeof METRIC_DEFINITIONS;

export interface MetricTooltipProps {
  /** Key into the shared definitions. */
  metric?: string;
  /** Overrides the shared definition — use the API's `definition` when present. */
  definition?: string | null;
  children?: React.ReactNode;
  className?: string;
  /** Renders the trigger as a small info icon instead of wrapping children. */
  iconOnly?: boolean;
  label?: string;
}

export function MetricTooltip({
  metric,
  definition,
  children,
  className,
  iconOnly,
  label,
}: MetricTooltipProps) {
  const text = definition ?? (metric ? METRIC_DEFINITIONS[metric] : undefined);
  if (!text) return <>{children}</>;

  if (iconOnly) {
    return (
      <Tooltip content={text}>
        <button
          type="button"
          aria-label={label ? `About ${label}` : 'About this metric'}
          className={cn('rounded-sm text-text-subtle hover:text-text-muted', className)}
        >
          <Info aria-hidden="true" className="size-3.5" />
        </button>
      </Tooltip>
    );
  }

  return (
    <Tooltip content={text}>
      <span
        className={cn(
          // Dotted underline is the long-standing convention for "there is a
          // definition here"; it also survives a greyscale check.
          'cursor-help underline decoration-dotted decoration-from-font underline-offset-4',
          className,
        )}
      >
        {children}
      </span>
    </Tooltip>
  );
}
