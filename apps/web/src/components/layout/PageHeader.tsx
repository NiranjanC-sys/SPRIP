'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';
import { Breadcrumb, type Crumb } from '@/components/ui/breadcrumb';
import { Skeleton } from '@/components/ui/skeleton';
import { SyntheticDataBadge } from '@/components/data/SyntheticDataBadge';
import { useSession } from '@/lib/api/queries/session';

/**
 * The page header every route renders.
 *
 * `<h1>` lives here and nowhere else, so each page has exactly one and the
 * heading outline stays sane. The synthetic badge is baked in rather than left
 * to each page, because a marking that pages opt into is a marking some page
 * will forget (plan.md §11).
 *
 * `actions` is a slot rather than a prop list: the dashboard pages need wildly
 * different controls — export, run scenario, submit for review — and enumerating
 * them here would make this component grow a branch per page.
 */

export interface PageHeaderProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  breadcrumbs?: readonly Crumb[];
  actions?: React.ReactNode;
  /** Rendered under the title row — filter bars, tabs, evidence summaries. */
  children?: React.ReactNode;
  /** Shown beside the title: status, evidence grade, lineage chip. */
  meta?: React.ReactNode;
  loading?: boolean;
  className?: string;
  /** Escape hatch for the rare page that marks synthetic data itself. */
  hideSyntheticBadge?: boolean;
}

export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  children,
  meta,
  loading,
  className,
  hideSyntheticBadge,
}: PageHeaderProps) {
  const { data: session } = useSession();
  const synthetic = session?.activeTenant?.syntheticMode ?? false;

  return (
    <div className={cn('flex flex-col gap-3 border-b border-border bg-surface px-4 py-4', className)}>
      {breadcrumbs && breadcrumbs.length > 0 ? <Breadcrumb items={breadcrumbs} /> : null}

      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {loading ? (
              <Skeleton className="h-7 w-64" label="Loading page title" />
            ) : (
              <h1 className="min-w-0 truncate text-xl font-semibold tracking-tight text-text">
                {title}
              </h1>
            )}
            {!hideSyntheticBadge ? <SyntheticDataBadge active={synthetic} /> : null}
            {meta}
          </div>
          {description ? (
            <p className="mt-1 max-w-3xl text-sm leading-relaxed text-text-muted">{description}</p>
          ) : null}
        </div>

        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>

      {children}
    </div>
  );
}
