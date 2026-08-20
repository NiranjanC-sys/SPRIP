import { cn } from '@/lib/utils';

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Sets `aria-hidden` off and adds a live-region label. Use once per region, not per bar. */
  label?: string;
}

/**
 * Loading placeholder. Individually `aria-hidden` — a screen reader hearing
 * fourteen "loading" nodes learns nothing; the containing region announces once.
 */
export function Skeleton({ className, label, ...props }: SkeletonProps) {
  return (
    <div
      role={label ? 'status' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn('animate-shimmer rounded-md bg-skeleton', className)}
      {...props}
    />
  );
}

/** Common composite: a block of text lines of decreasing width. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn('h-3.5', i === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  );
}
