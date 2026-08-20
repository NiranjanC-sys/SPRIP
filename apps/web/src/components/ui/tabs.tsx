'use client';

import * as React from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';

import { cn } from '@/lib/utils';

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List> & { variant?: 'underline' | 'pill' }
>(function TabsList({ className, variant = 'underline', ...props }, ref) {
  return (
    <TabsPrimitive.List
      ref={ref}
      data-variant={variant}
      className={cn(
        'flex items-center',
        variant === 'underline'
          ? 'gap-4 border-b border-border'
          : 'gap-1 rounded-md border border-border bg-surface-sunken p-1',
        className,
      )}
      {...props}
    />
  );
});

export const TabsTrigger = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(function TabsTrigger({ className, ...props }, ref) {
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        'inline-flex items-center gap-2 whitespace-nowrap text-sm font-medium text-text-muted transition-colors',
        'disabled:pointer-events-none disabled:opacity-50',
        // Underline variant: the active indicator is a 2px border, not a colour
        // change alone, so it survives a greyscale check.
        '-mb-px border-b-2 border-transparent pb-2 pt-1 data-[state=active]:border-primary data-[state=active]:text-text',
        '[[data-variant=pill]_&]:mb-0 [[data-variant=pill]_&]:rounded-sm [[data-variant=pill]_&]:border-0 [[data-variant=pill]_&]:px-3 [[data-variant=pill]_&]:py-1 [[data-variant=pill]_&]:data-[state=active]:bg-surface [[data-variant=pill]_&]:data-[state=active]:shadow-sm',
        className,
      )}
      {...props}
    />
  );
});

export const TabsContent = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(function TabsContent({ className, ...props }, ref) {
  return <TabsPrimitive.Content ref={ref} className={cn('mt-4 outline-none', className)} {...props} />;
});
