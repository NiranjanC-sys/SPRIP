'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

export const inputBaseClass = cn(
  'flex h-9 w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-text',
  'shadow-sm transition-colors',
  'placeholder:text-text-subtle',
  'hover:border-border-strong',
  'disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:opacity-60',
  'aria-invalid:border-danger aria-invalid:hover:border-danger',
  'file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-text',
);

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Leading adornment (icon). Purely decorative — give the field a real label. */
  iconLeft?: React.ReactNode;
  /** Trailing adornment; sized to fit a small IconButton. */
  slotRight?: React.ReactNode;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, type = 'text', iconLeft, slotRight, ...props },
  ref,
) {
  if (!iconLeft && !slotRight) {
    return <input ref={ref} type={type} className={cn(inputBaseClass, className)} {...props} />;
  }

  return (
    <div className="relative flex w-full items-center">
      {iconLeft ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute left-3 flex items-center text-text-subtle [&_svg]:size-4"
        >
          {iconLeft}
        </span>
      ) : null}
      <input
        ref={ref}
        type={type}
        className={cn(inputBaseClass, iconLeft && 'pl-9', slotRight && 'pr-9', className)}
        {...props}
      />
      {slotRight ? <span className="absolute right-1 flex items-center">{slotRight}</span> : null}
    </div>
  );
});
