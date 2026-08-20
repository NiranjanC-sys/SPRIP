'use client';

import * as React from 'react';
import Link from 'next/link';
import {
  Bell,
  CircleAlert,
  CircleCheck,
  Info,
  ShieldCheck,
  TriangleAlert,
  UploadCloud,
  Workflow,
} from 'lucide-react';

import type { NotificationItem } from '@/lib/api/types';
import { useMarkNotificationsRead, useNotifications } from '@/lib/api/queries/shell';
import { formatRelativeTime } from '@/lib/formatters';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { IconButton } from '@/components/ui/icon-button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { SkeletonText } from '@/components/ui/skeleton';
import { EmptyState, ErrorState } from '@/components/data/states';

/**
 * Operational notifications: a run finished, an upload failed validation, a
 * result is waiting on your review.
 *
 * Not a marketing feed. Everything here is something the recipient is expected
 * to act on, which is why unread state is server-side (you should not lose your
 * queue by opening the app on a different machine) and why each item carries a
 * link straight to the thing that needs attention.
 */

const KIND_ICON = {
  RUN: Workflow,
  UPLOAD: UploadCloud,
  REVIEW: ShieldCheck,
  SYSTEM: Info,
} as const;

const SEVERITY_ICON = {
  INFO: Info,
  SUCCESS: CircleCheck,
  WARNING: TriangleAlert,
  ERROR: CircleAlert,
} as const;

const SEVERITY_CLASS = {
  INFO: 'text-info',
  SUCCESS: 'text-positive',
  WARNING: 'text-warning',
  ERROR: 'text-danger',
} as const;

export function NotificationCenter({ className }: { className?: string }) {
  const [open, setOpen] = React.useState(false);
  const query = useNotifications(false);
  const markRead = useMarkNotificationsRead();

  const items = query.data?.items ?? [];
  const unread = items.filter((n) => n.readAt === null);

  const markAll = () => {
    if (unread.length > 0) markRead.mutate(unread.map((n) => n.notificationId));
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <IconButton
          label={
            unread.length > 0
              ? `Notifications, ${unread.length} unread`
              : 'Notifications, none unread'
          }
          variant="ghost"
          size="sm"
          className={cn('relative', className)}
        >
          <Bell />
          {unread.length > 0 ? (
            // The count is in the accessible name above; this dot is decoration
            // for sighted users and must not be announced twice.
            <span
              aria-hidden="true"
              // `text-surface` rather than a literal white: in dark mode the
              // danger token is a light coral, and white-on-coral fails AA.
              className="absolute right-1 top-1 flex size-3.5 items-center justify-center rounded-full bg-danger font-mono text-[9px] font-bold leading-none text-surface"
            >
              {unread.length > 9 ? '9+' : unread.length}
            </span>
          ) : null}
        </IconButton>
      </PopoverTrigger>

      <PopoverContent align="end" className="w-96 p-0">
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          <p className="text-sm font-semibold text-text">Notifications</p>
          {unread.length > 0 ? (
            <Button variant="link" size="sm" onClick={markAll} loading={markRead.isPending}>
              Mark all read
            </Button>
          ) : null}
        </div>

        <div className="scroll-thin max-h-96 overflow-y-auto">
          {query.isPending ? (
            <div className="p-3">
              <SkeletonText lines={4} />
            </div>
          ) : query.isError ? (
            <ErrorState compact error={query.error} onRetry={() => void query.refetch()} />
          ) : items.length === 0 ? (
            <EmptyState
              compact
              icon={<Bell />}
              title="Nothing needs you"
              description="Run failures, validation errors and review requests appear here."
            />
          ) : (
            <ul className="divide-y divide-border">
              {items.map((item) => (
                <NotificationRow
                  key={item.notificationId}
                  item={item}
                  onOpen={() => {
                    if (item.readAt === null) markRead.mutate([item.notificationId]);
                    setOpen(false);
                  }}
                />
              ))}
            </ul>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function NotificationRow({ item, onOpen }: { item: NotificationItem; onOpen: () => void }) {
  const KindIcon = KIND_ICON[item.kind];
  const SeverityIcon = SEVERITY_ICON[item.severity];
  const unread = item.readAt === null;

  const body = (
    <>
      <span className="relative mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-surface-sunken">
        <KindIcon aria-hidden="true" className="size-3.5 text-text-subtle" />
        <SeverityIcon
          aria-hidden="true"
          className={cn(
            'absolute -bottom-0.5 -right-0.5 size-3 rounded-full bg-surface-raised',
            SEVERITY_CLASS[item.severity],
          )}
        />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2">
          <span className={cn('truncate text-sm', unread ? 'font-semibold text-text' : 'text-text-muted')}>
            {item.title}
          </span>
          <span className="shrink-0 text-2xs text-text-subtle">
            {formatRelativeTime(item.createdAt)}
          </span>
        </span>
        {item.body ? (
          <span className="mt-0.5 block text-xs leading-relaxed text-text-muted">{item.body}</span>
        ) : null}
      </span>
      {unread ? (
        <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" />
      ) : null}
    </>
  );

  const className = cn(
    'flex w-full items-start gap-2.5 px-3 py-2.5 text-left',
    unread ? 'bg-primary/5' : 'bg-transparent',
    'hover:bg-surface-sunken',
  );

  return (
    <li>
      {item.href ? (
        <Link href={item.href} onClick={onOpen} className={className}>
          {body}
        </Link>
      ) : (
        <button type="button" onClick={onOpen} className={className}>
          {body}
        </button>
      )}
      {unread ? <span className="sr-only">Unread</span> : null}
    </li>
  );
}
