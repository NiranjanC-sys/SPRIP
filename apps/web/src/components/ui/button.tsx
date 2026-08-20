'use client';

import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';
import { Spinner } from './spinner';

/**
 * The focus ring is declared once globally in globals.css (`:focus-visible`), so
 * variants here never redefine it — one ring definition means one thing to audit
 * for the WCAG 2.1 AA non-text-contrast criterion.
 */
const buttonVariants = cva(
  [
    'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md',
    'font-medium transition-colors duration-150',
    'disabled:pointer-events-none disabled:opacity-50',
    '[&_svg]:pointer-events-none [&_svg]:shrink-0',
  ].join(' '),
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-fg hover:bg-primary-hover',
        secondary: 'border border-border-strong bg-surface text-text hover:bg-surface-sunken',
        ghost: 'text-text-muted hover:bg-surface-sunken hover:text-text',
        danger: 'bg-danger text-primary-fg hover:brightness-95',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-8 px-2.5 text-xs [&_svg]:size-3.5',
        md: 'h-9 px-3.5 text-sm [&_svg]:size-4',
        lg: 'h-11 px-5 text-sm [&_svg]:size-4',
      },
      block: { true: 'w-full', false: '' },
    },
    defaultVariants: { variant: 'secondary', size: 'md', block: false },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render as the single child element (Radix `asChild`) — e.g. wrap a `<Link>`. */
  asChild?: boolean;
  loading?: boolean;
  /** Announced while `loading`. Defaults to the button's own label being kept. */
  loadingLabel?: string;
  iconLeft?: React.ReactNode;
  iconRight?: React.ReactNode;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    className,
    variant,
    size,
    block,
    asChild = false,
    loading = false,
    loadingLabel = 'Working',
    iconLeft,
    iconRight,
    children,
    disabled,
    type,
    ...props
  },
  ref,
) {
  const Comp = asChild ? Slot : 'button';
  return (
    <Comp
      ref={ref}
      // Default to "button": an unset type inside a form submits it, which has
      // caused real double-submits on the upload screens.
      type={asChild ? undefined : (type ?? 'button')}
      className={cn(buttonVariants({ variant, size, block }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Spinner size={size === 'lg' ? 'md' : 'sm'} label={loadingLabel} /> : iconLeft}
      {children}
      {loading ? null : iconRight}
    </Comp>
  );
});

export { buttonVariants };
