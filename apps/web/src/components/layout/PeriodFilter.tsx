'use client';

import * as React from 'react';
import { CalendarRange, Check } from 'lucide-react';

import { formatMonth } from '@/lib/formatters';
import { useUrlFilters } from '@/lib/urlState';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Separator } from '@/components/ui/separator';

/**
 * The global period selector.
 *
 * Months, not days. Every outcome panel in this product is monthly (plan.md §6),
 * so a day-granular picker would promise a resolution the data does not have and
 * quietly round behind the user's back.
 *
 * The presets are expressed as month offsets from the current month rather than
 * as fixed dates, so "last 12 months" keeps meaning that tomorrow. They are
 * ranges over the calendar, not business figures — no analytical constant is
 * hard-coded here.
 */

const PRESETS = [
  { id: 'last-3', label: 'Last 3 months', months: 3 },
  { id: 'last-6', label: 'Last 6 months', months: 6 },
  { id: 'last-12', label: 'Last 12 months', months: 12 },
  { id: 'last-24', label: 'Last 24 months', months: 24 },
] as const;

function monthKey(date: Date): string {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`;
}

function presetRange(months: number): { from: string; to: string } {
  const now = new Date();
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - (months - 1), 1));
  return { from: monthKey(start), to: monthKey(end) };
}

export interface PeriodFilterProps {
  /** Bounds of the tenant's outcome panel, from `filterOptions`. */
  min?: string | null;
  max?: string | null;
  className?: string;
}

export function PeriodFilter({ min, max, className }: PeriodFilterProps) {
  const url = useUrlFilters();
  const [open, setOpen] = React.useState(false);

  const from = url.get('from');
  const to = url.get('to');
  const [draftFrom, setDraftFrom] = React.useState(from ?? '');
  const [draftTo, setDraftTo] = React.useState(to ?? '');

  React.useEffect(() => {
    setDraftFrom(from ?? '');
    setDraftTo(to ?? '');
  }, [from, to]);

  const label =
    from && to
      ? `${formatMonth(from)} – ${formatMonth(to)}`
      : from
        ? `From ${formatMonth(from)}`
        : to
          ? `Through ${formatMonth(to)}`
          : 'All periods';

  const activePreset = PRESETS.find((preset) => {
    const range = presetRange(preset.months);
    return range.from === from && range.to === to;
  });

  const apply = (nextFrom: string, nextTo: string) => {
    url.set({ from: nextFrom || null, to: nextTo || null });
    setOpen(false);
  };

  // Reversed bounds are a user slip, not an error worth a toast — swap them.
  const applyDraft = () => {
    if (draftFrom && draftTo && draftFrom > draftTo) apply(draftTo, draftFrom);
    else apply(draftFrom, draftTo);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="secondary"
          size="sm"
          className={cn('gap-2 font-normal', className)}
          iconLeft={<CalendarRange />}
          aria-label={`Reporting period: ${label}`}
        >
          <span className="hidden text-text-muted md:inline">Period</span>
          <span className="font-medium text-text">{activePreset?.label ?? label}</span>
        </Button>
      </PopoverTrigger>

      <PopoverContent align="end" className="w-72">
        <p className="text-2xs font-semibold uppercase tracking-wide text-text-subtle">Presets</p>
        <ul className="mt-1.5 flex flex-col gap-0.5">
          {PRESETS.map((preset) => {
            const selected = activePreset?.id === preset.id;
            return (
              <li key={preset.id}>
                <button
                  type="button"
                  onClick={() => {
                    const range = presetRange(preset.months);
                    apply(range.from, range.to);
                  }}
                  className={cn(
                    'flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-sm text-text hover:bg-surface-sunken',
                    selected && 'font-medium',
                  )}
                >
                  {preset.label}
                  {selected ? (
                    <Check aria-hidden="true" className="size-3.5 text-primary" strokeWidth={3} />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>

        <Separator className="my-3" />

        <p className="text-2xs font-semibold uppercase tracking-wide text-text-subtle">Custom</p>
        <div className="mt-1.5 grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 text-xs text-text-muted">
            From
            <Input
              type="month"
              value={draftFrom}
              min={min ?? undefined}
              max={max ?? undefined}
              onChange={(e) => setDraftFrom(e.target.value)}
              className="h-8 text-xs"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-text-muted">
            To
            <Input
              type="month"
              value={draftTo}
              min={min ?? undefined}
              max={max ?? undefined}
              onChange={(e) => setDraftTo(e.target.value)}
              className="h-8 text-xs"
            />
          </label>
        </div>

        {min || max ? (
          <p className="mt-2 text-2xs text-text-subtle">
            Outcome data available {min ? formatMonth(min) : '—'} to {max ? formatMonth(max) : '—'}.
          </p>
        ) : null}

        <div className="mt-3 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => apply('', '')}>
            Clear
          </Button>
          <Button size="sm" onClick={applyDraft}>
            Apply
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
