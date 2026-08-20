'use client';

import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';
import { Spinner } from './spinner';

const iconButtonVariants = cva(
  'inline-flex items-center justify-center rounded-md transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-fg hover:bg-primary-hover',
        secondary: 'border border-border-strong bg-surface text-text hover:bg-surface-sunken',
        ghost: 'text-text-muted hover:bg-surface-sunken hover:text-text',
        danger: 'text-danger hover:bg-danger-soft',
        /** For use on the dark navy nav in both themes. */
        nav: 'text-nav-fg hover:bg-nav-active-bg hover:text-nav-fg-active',
      },
      size: {
        sm: 'size-7 [&_svg]:size-3.5',
        md: 'size-9 [&_svg]:size-4',
        lg: 'size-11 [&_svg]:size-5',
      },
    },
    defaultVariants: { variant: 'ghost', size: 'md' },
  },
);

export interface IconButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof iconButtonVariants> {
  asChild?: boolean;
  loading?: boolean;
  /**
   * Required. An icon-only control with no accessible name is the single most
   * common a11y defect in dashboards, so the type system refuses to let one ship.
   */
  label: string;
}

export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { className, variant, size, asChild = false, loading = false, label, children, disabled, type, ...props },
  ref,
) {
  const Comp = asChild ? Slot : 'button';
  return (
    <Comp
      ref={ref}
      type={asChild ? undefined : (type ?? 'button')}
      aria-label={label}
      title={label}
      className={cn(iconButtonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Spinner size="sm" /> : children}
    </Comp>
  );
});
