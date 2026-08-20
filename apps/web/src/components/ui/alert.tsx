import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const alertVariants = cva('flex gap-3 rounded-md border p-3 text-sm', {
  variants: {
    tone: {
      info: 'border-info/30 bg-info-soft text-text',
      positive: 'border-positive/30 bg-positive-soft text-text',
      warning: 'border-warning/40 bg-warning-soft text-text',
      danger: 'border-danger/40 bg-danger-soft text-text',
      neutral: 'border-border bg-surface-sunken text-text',
    },
  },
  defaultVariants: { tone: 'info' },
});

const ICONS = {
  info: Info,
  positive: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
  neutral: Info,
} as const;

const ICON_TONE = {
  info: 'text-info',
  positive: 'text-positive',
  warning: 'text-warning',
  danger: 'text-danger',
  neutral: 'text-text-muted',
} as const;

export interface AlertProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'>,
    VariantProps<typeof alertVariants> {
  title?: React.ReactNode;
  /** Buttons or links rendered under the body. */
  actions?: React.ReactNode;
  icon?: React.ReactNode;
}

export function Alert({ className, tone = 'info', title, actions, icon, children, ...props }: AlertProps) {
  const resolved = tone ?? 'info';
  const Icon = ICONS[resolved];
  return (
    <div
      // `alert` interrupts; reserve it for the two tones that mean something
      // went wrong, so routine info banners do not hijack the screen reader.
      role={resolved === 'danger' || resolved === 'warning' ? 'alert' : 'status'}
      className={cn(alertVariants({ tone }), className)}
      {...props}
    >
      <span aria-hidden="true" className={cn('mt-0.5 shrink-0', ICON_TONE[resolved])}>
        {icon ?? <Icon className="size-4" />}
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        {title ? <p className="font-semibold leading-tight">{title}</p> : null}
        {children ? <div className="text-sm leading-relaxed text-text-muted">{children}</div> : null}
        {actions ? <div className="mt-1 flex flex-wrap gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}
