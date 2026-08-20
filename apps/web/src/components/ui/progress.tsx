'use client';

import * as React from 'react';
import * as ProgressPrimitive from '@radix-ui/react-progress';

import { cn } from '@/lib/utils';

export interface ProgressProps
  extends Omit<React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>, 'value'> {
  /** 0–1. `null` renders the indeterminate state. */
  value: number | null;
  tone?: 'primary' | 'positive' | 'warning' | 'danger';
  size?: 'sm' | 'md';
  /** Required: a bare bar has no accessible name. */
  label: string;
}

const TONE = {
  primary: 'bg-primary',
  positive: 'bg-positive',
  warning: 'bg-warning',
  danger: 'bg-danger',
} as const;

export const Progress = React.forwardRef<
  React.ComponentRef<typeof ProgressPrimitive.Root>,
  ProgressProps
>(function Progress({ className, value, tone = 'primary', size = 'md', label, ...props }, ref) {
  const pct = value === null ? null : Math.min(100, Math.max(0, value * 100));
  return (
    <ProgressPrimitive.Root
      ref={ref}
      value={pct}
      aria-label={label}
      className={cn(
        'relative w-full overflow-hidden rounded-full bg-surface-sunken',
        size === 'sm' ? 'h-1' : 'h-1.5',
        className,
      )}
      {...props}
    >
      {pct === null ? (
        // Indeterminate: a sliding band. Radix leaves aria-valuenow unset, which
        // is exactly right — "we do not know how far along this is".
        <div className={cn('absolute inset-y-0 w-1/3 animate-indeterminate rounded-full', TONE[tone])} />
      ) : (
        <ProgressPrimitive.Indicator
          className={cn('h-full w-full flex-1 transition-transform duration-300', TONE[tone])}
          style={{ transform: `translateX(-${100 - pct}%)` }}
        />
      )}
    </ProgressPrimitive.Root>
  );
});
