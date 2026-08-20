import { cn } from '@/lib/utils';

/** Keyboard hint. Mono face keeps ⌘K and Ctrl K the same optical weight. */
export function Kbd({ className, children, ...props }: React.HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        'inline-flex h-5 min-w-5 items-center justify-center rounded-sm border border-border bg-surface-sunken px-1.5',
        'font-mono text-2xs font-medium text-text-muted',
        className,
      )}
      {...props}
    >
      {children}
    </kbd>
  );
}
