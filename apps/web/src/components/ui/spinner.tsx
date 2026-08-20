import { Loader2 } from 'lucide-react';

import { cn } from '@/lib/utils';

const SIZES = { sm: 'size-3.5', md: 'size-4', lg: 'size-5', xl: 'size-8' } as const;

export interface SpinnerProps extends React.SVGProps<SVGSVGElement> {
  size?: keyof typeof SIZES;
  /** Announce to screen readers. Omit inside a control that already announces busy state. */
  label?: string;
}

export function Spinner({ size = 'md', label, className, ...props }: SpinnerProps) {
  return (
    <>
      <Loader2
        aria-hidden="true"
        className={cn('animate-spin motion-reduce:animate-none', SIZES[size], className)}
        {...props}
      />
      {label ? <span className="sr-only">{label}</span> : null}
    </>
  );
}
