'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, rows = 4, ...props },
  ref,
) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      className={cn(
        'flex w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text',
        'shadow-sm transition-colors placeholder:text-text-subtle',
        'hover:border-border-strong',
        'disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:opacity-60',
        'aria-invalid:border-danger',
        className,
      )}
      {...props}
    />
  );
});
