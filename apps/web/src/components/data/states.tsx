'use client';

import * as React from 'react';
import Link from 'next/link';
import {
  AlertTriangle,
  FileQuestion,
  Inbox,
  Lock,
  RefreshCw,
  ScatterChart,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { toDisplayMessage, toRequestId } from '@/lib/api/errors';
import { Button } from '@/components/ui/button';
import { CopyButton } from '@/components/ui/copy-button';

/**
 * The five terminal states every data surface must handle.
 *
 * They exist as named components rather than ad-hoc markup because the
 * difference between them is a product decision, not a styling one:
 *
 *   empty                → the query is valid, there is nothing to show
 *   error                → we failed; the user can retry
 *   forbidden            → the user may not see this; we do not say what "this" is
 *   insufficient-evidence→ the data exists but does not meet the gates, so we
 *                          refuse to show a number (PLAN_REVIEW F-9)
 *   loading              → skeletons, handled per-surface
 *
 * Conflating "empty" with "insufficient evidence" is the specific failure mode
 * this product cannot have: an analyst reading "no data" where the answer is
 * actually "we cannot estimate this reliably" will draw the wrong conclusion.
 */

interface StateShellProps {
  icon: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  tone?: 'neutral' | 'warning' | 'danger';
  className?: string;
  compact?: boolean;
  children?: React.ReactNode;
}

const TONE_RING = {
  neutral: 'bg-surface-sunken text-text-subtle',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
} as const;

function StateShell({
  icon,
  title,
  description,
  actions,
  tone = 'neutral',
  className,
  compact,
  children,
}: StateShellProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 text-center',
        compact ? 'px-4 py-8' : 'px-6 py-14',
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn('flex size-10 items-center justify-center rounded-full [&_svg]:size-5', TONE_RING[tone])}
      >
        {icon}
      </span>
      <div className="flex max-w-md flex-col gap-1.5">
        <p className="text-sm font-semibold text-text">{title}</p>
        {description ? (
          <div className="text-sm leading-relaxed text-text-muted">{description}</div>
        ) : null}
      </div>
      {children}
      {actions ? <div className="flex flex-wrap justify-center gap-2">{actions}</div> : null}
    </div>
  );
}

/* --- empty ---------------------------------------------------------------- */

export interface EmptyStateProps {
  title?: string;
  description?: React.ReactNode;
  actionLabel?: string;
  onAction?: () => void;
  actionHref?: string;
  icon?: React.ReactNode;
  className?: string;
  compact?: boolean;
}

export function EmptyState({
  title = 'Nothing to show',
  description = 'No records match the current filters.',
  actionLabel,
  onAction,
  actionHref,
  icon,
  className,
  compact,
}: EmptyStateProps) {
  const action = actionLabel ? (
    actionHref ? (
      <Button asChild variant="secondary" size="sm">
        <Link href={actionHref}>{actionLabel}</Link>
      </Button>
    ) : (
      <Button variant="secondary" size="sm" onClick={onAction}>
        {actionLabel}
      </Button>
    )
  ) : null;

  return (
    <StateShell
      icon={icon ?? <Inbox />}
      title={title}
      description={description}
      actions={action}
      className={className}
      compact={compact}
    />
  );
}

/* --- error ---------------------------------------------------------------- */

export interface ErrorStateProps {
  error?: unknown;
  title?: string;
  description?: React.ReactNode;
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
}

export function ErrorState({
  error,
  title = 'Something went wrong',
  description,
  onRetry,
  className,
  compact,
}: ErrorStateProps) {
  const message = description ?? (error ? toDisplayMessage(error) : 'The request could not be completed.');
  const requestId = error ? toRequestId(error) : null;

  return (
    <StateShell
      icon={<AlertTriangle />}
      tone="danger"
      title={title}
      description={message}
      className={className}
      compact={compact}
      actions={
        onRetry ? (
          <Button variant="secondary" size="sm" onClick={onRetry} iconLeft={<RefreshCw />}>
            Try again
          </Button>
        ) : null
      }
    >
      {requestId ? (
        // Support cannot correlate a screenshot to a log line without this, and
        // asking a user to read a UUID aloud is not a support process.
        <p className="flex items-center gap-1 text-2xs text-text-subtle">
          <span>Reference</span>
          <code className="font-mono">{requestId}</code>
          <CopyButton value={requestId} label="Copy reference" size="sm" />
        </p>
      ) : null}
    </StateShell>
  );
}

/* --- forbidden ------------------------------------------------------------ */

export interface ForbiddenStateProps {
  /** Deliberately no `resource` prop — see the note below. */
  title?: string;
  description?: React.ReactNode;
  className?: string;
  compact?: boolean;
}

/**
 * 403. The copy never names the resource, the tenant, or the role that would
 * grant access: an authorization error that describes what it is protecting is
 * an enumeration oracle. "Ask your administrator" is the whole message.
 */
export function ForbiddenState({
  title = 'You do not have access to this',
  description = 'If you believe you should, ask your organisation administrator to review your role.',
  className,
  compact,
}: ForbiddenStateProps) {
  return (
    <StateShell
      icon={<Lock />}
      tone="warning"
      title={title}
      description={description}
      className={className}
      compact={compact}
    />
  );
}

/* --- insufficient evidence ------------------------------------------------ */

export interface InsufficientEvidenceStateProps {
  /** Human-readable gate names that failed, from the evidence summary. */
  failedGates?: readonly string[];
  reason?: string | null;
  className?: string;
  compact?: boolean;
  /** Link to the methodology page explaining the gates. */
  methodologyHref?: string;
}

/**
 * The refusal state.
 *
 * PLAN_REVIEW F-9 and plan.md §7.0: when the hard gates are not met we report
 * NOT_RELIABLY_ESTIMABLE, never a zero and never a point estimate with a
 * disclaimer. This component is how that refusal reaches the screen, and it
 * always says *which* gate failed — a refusal the reader cannot act on is just
 * a broken page.
 */
export function InsufficientEvidenceState({
  failedGates,
  reason,
  className,
  compact,
  methodologyHref = '/data-health',
}: InsufficientEvidenceStateProps) {
  return (
    <StateShell
      icon={<ScatterChart />}
      tone="warning"
      title="Not reliably estimable"
      description={
        reason ??
        'The evidence gates for this selection were not met, so no estimate is reported. This is not a result of zero.'
      }
      className={className}
      compact={compact}
      actions={
        <Button asChild variant="link" size="sm">
          <Link href={methodologyHref}>How evidence is graded</Link>
        </Button>
      }
    >
      {failedGates && failedGates.length > 0 ? (
        <ul className="flex flex-col gap-1 text-xs text-text-muted">
          {failedGates.map((gate) => (
            <li key={gate} className="flex items-center justify-center gap-1.5">
              <span aria-hidden="true" className="size-1 rounded-full bg-warning" />
              {gate}
            </li>
          ))}
        </ul>
      ) : null}
    </StateShell>
  );
}

/* --- not found ------------------------------------------------------------ */

export function NotFoundState({
  title = 'Not found',
  description = 'This record may have been removed, or the link may be out of date.',
  className,
  compact,
}: {
  title?: string;
  description?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <StateShell
      icon={<FileQuestion />}
      title={title}
      description={description}
      className={className}
      compact={compact}
    />
  );
}
