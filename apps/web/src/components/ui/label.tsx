'use client';

import * as React from 'react';
import * as LabelPrimitive from '@radix-ui/react-label';

import { cn } from '@/lib/utils';

export interface LabelProps extends React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root> {
  required?: boolean;
}

export const Label = React.forwardRef<
  React.ComponentRef<typeof LabelPrimitive.Root>,
  LabelProps
>(function Label({ className, required, children, ...props }, ref) {
  return (
    <LabelPrimitive.Root
      ref={ref}
      className={cn(
        'text-sm font-medium leading-none text-text peer-disabled:cursor-not-allowed peer-disabled:opacity-60',
        className,
      )}
      {...props}
    >
      {children}
      {required ? (
        <>
          <span aria-hidden="true" className="ml-0.5 text-danger">
            *
          </span>
          {/* The asterisk alone is a colour-and-glyph convention; spell it out. */}
          <span className="sr-only"> (required)</span>
        </>
      ) : null}
    </LabelPrimitive.Root>
  );
});
