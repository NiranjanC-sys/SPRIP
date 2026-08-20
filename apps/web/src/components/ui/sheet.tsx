'use client';

import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';

import { cn } from '@/lib/utils';
import { IconButton } from './icon-button';

/**
 * Edge-anchored panel. Built on Dialog because a sheet is a modal with different
 * geometry — same focus trap, same escape handling, same `aria-modal`.
 */

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

const SIDE = {
  right: 'inset-y-0 right-0 h-full border-l',
  left: 'inset-y-0 left-0 h-full border-r',
  bottom: 'inset-x-0 bottom-0 max-h-[85vh] border-t',
} as const;

const WIDTH = {
  sm: 'w-full sm:max-w-sm',
  md: 'w-full sm:max-w-md',
  lg: 'w-full sm:max-w-xl',
  xl: 'w-full sm:max-w-3xl',
} as const;

export interface SheetContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  side?: keyof typeof SIDE;
  size?: keyof typeof WIDTH;
}

export const SheetContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  SheetContentProps
>(function SheetContent({ className, children, side = 'right', size = 'md', ...props }, ref) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-overlay backdrop-blur-[2px]" />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(
          'fixed z-50 flex flex-col border-border bg-surface-raised shadow-lg',
          SIDE[side],
          side === 'bottom' ? 'w-full rounded-t-lg' : WIDTH[size],
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close asChild>
          <IconButton label="Close" size="sm" className="absolute right-3 top-3">
            <X />
          </IconButton>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
});

export function SheetHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex flex-col gap-1 border-b border-border p-4 pr-12', className)} {...props} />;
}

export const SheetTitle = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(function SheetTitle({ className, ...props }, ref) {
  return (
    <DialogPrimitive.Title
      ref={ref}
      className={cn('text-base font-semibold leading-tight text-text', className)}
      {...props}
    />
  );
});

export const SheetDescription = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(function SheetDescription({ className, ...props }, ref) {
  return (
    <DialogPrimitive.Description
      ref={ref}
      className={cn('text-sm leading-relaxed text-text-muted', className)}
      {...props}
    />
  );
});

export function SheetBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('scroll-thin min-h-0 flex-1 overflow-y-auto p-4', className)} {...props} />;
}

export function SheetFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex flex-col-reverse gap-2 border-t border-border p-4 sm:flex-row sm:justify-end', className)}
      {...props}
    />
  );
}
