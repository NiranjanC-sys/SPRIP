import { cn } from '@/lib/utils';

/**
 * Quieter than `Alert`: an inline annotation attached to a chart or figure —
 * "estimated on 41 of 52 events", "control cohort capped this grade at
 * MODERATE". Not a live region; it is part of the reading order, not an
 * interruption.
 */
export interface CalloutProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: React.ReactNode;
  tone?: 'neutral' | 'info' | 'warning';
}

const TONE = {
  neutral: 'border-border bg-surface-sunken',
  info: 'border-info/25 bg-info-soft',
  warning: 'border-warning/35 bg-warning-soft',
} as const;

export function Callout({ className, icon, tone = 'neutral', children, ...props }: CalloutProps) {
  return (
    <div
      className={cn(
        'flex items-start gap-2 rounded-md border px-3 py-2 text-xs leading-relaxed text-text-muted',
        TONE[tone],
        className,
      )}
      {...props}
    >
      {icon ? (
        <span aria-hidden="true" className="mt-px shrink-0 [&_svg]:size-3.5">
          {icon}
        </span>
      ) : null}
      <div className="min-w-0">{children}</div>
    </div>
  );
}
