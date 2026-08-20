import { cn } from '@/lib/utils';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Raised surface for panels that float above the page (popovers, drawers). */
  raised?: boolean;
  /** Removes the outer padding so a table can bleed to the card edge. */
  flush?: boolean;
}

export function Card({ className, raised, flush, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'rounded-lg border border-border text-text',
        raised ? 'bg-surface-raised shadow-md' : 'bg-surface shadow-sm',
        flush && 'overflow-hidden',
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  className,
  bordered,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { bordered?: boolean }) {
  return (
    <div
      className={cn(
        'flex flex-col gap-1 p-4',
        bordered && 'border-b border-border',
        className,
      )}
      {...props}
    />
  );
}

export function CardTitle({
  className,
  as: As = 'h3',
  ...props
}: React.HTMLAttributes<HTMLHeadingElement> & { as?: 'h2' | 'h3' | 'h4' }) {
  return <As className={cn('text-sm font-semibold leading-tight text-text', className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('text-xs leading-relaxed text-text-muted', className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-4 pt-0', className)} {...props} />;
}

export function CardFooter({
  className,
  bordered,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { bordered?: boolean }) {
  return (
    <div
      className={cn(
        'flex items-center gap-2 p-4 pt-0',
        bordered && 'border-t border-border pt-4',
        className,
      )}
      {...props}
    />
  );
}

/** Header with title on the left and actions on the right — the common case. */
export function CardToolbar({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex items-start justify-between gap-3 border-b border-border p-4', className)}
      {...props}
    />
  );
}
