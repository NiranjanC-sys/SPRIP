import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

/**
 * Colour is never the only signal here. Callers that convey *status* must use
 * `StatusBadge` (which always supplies an icon and a text label); this primitive
 * is for the neutral labelling cases — counts, tags, versions.
 */
const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-2xs font-medium leading-4 whitespace-nowrap [&_svg]:size-3 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        neutral: 'border-transparent bg-surface-sunken text-text-muted',
        info: 'border-transparent bg-info-soft text-info',
        positive: 'border-transparent bg-positive-soft text-positive',
        warning: 'border-transparent bg-warning-soft text-warning',
        danger: 'border-transparent bg-danger-soft text-danger',
        outline: 'border-border-strong bg-transparent text-text-muted',
      },
      size: {
        sm: 'px-1.5 py-0.5 text-2xs',
        md: 'px-2 py-1 text-xs leading-4',
      },
    },
    defaultVariants: { variant: 'neutral', size: 'sm' },
  },
);

export type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>['variant']>;

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, size, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, size }), className)} {...props} />;
}

export { badgeVariants };
