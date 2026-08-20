'use client';

import * as React from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';

import { cn } from '@/lib/utils';

export const TooltipProvider = TooltipPrimitive.Provider;
export const TooltipRoot = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export const TooltipContent = React.forwardRef<
  React.ComponentRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(function TooltipContent({ className, sideOffset = 6, children, ...props }, ref) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        ref={ref}
        sideOffset={sideOffset}
        className={cn(
          'z-50 max-w-72 rounded-md border border-border bg-surface-raised px-2.5 py-1.5 text-xs leading-relaxed text-text shadow-lg',
          className,
        )}
        {...props}
      >
        {children}
        <TooltipPrimitive.Arrow className="fill-[var(--surface-raised)]" width={10} height={5} />
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  );
});

export interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>['side'];
  align?: React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>['align'];
  /** Set when the trigger is not focusable (plain text): wraps it in a button. */
  asChild?: boolean;
  delayDuration?: number;
}

/**
 * Convenience wrapper. Tooltips must never be the only place information lives —
 * they are unavailable on touch and to some AT. Anything load-bearing (an
 * evidence grade, a refusal reason) also appears as visible text.
 */
export function Tooltip({
  content,
  children,
  side = 'top',
  align = 'center',
  asChild = true,
  delayDuration = 200,
}: TooltipProps) {
  return (
    <TooltipRoot delayDuration={delayDuration}>
      <TooltipTrigger asChild={asChild}>{children}</TooltipTrigger>
      <TooltipContent side={side} align={align}>
        {content}
      </TooltipContent>
    </TooltipRoot>
  );
}
