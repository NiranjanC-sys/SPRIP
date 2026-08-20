'use client';

import * as React from 'react';
import * as RadioGroupPrimitive from '@radix-ui/react-radio-group';

import { cn } from '@/lib/utils';

export const RadioGroup = React.forwardRef<
  React.ComponentRef<typeof RadioGroupPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Root>
>(function RadioGroup({ className, ...props }, ref) {
  return <RadioGroupPrimitive.Root ref={ref} className={cn('grid gap-2', className)} {...props} />;
});

export const RadioGroupItem = React.forwardRef<
  React.ComponentRef<typeof RadioGroupPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Item>
>(function RadioGroupItem({ className, ...props }, ref) {
  return (
    <RadioGroupPrimitive.Item
      ref={ref}
      className={cn(
        'aspect-square size-4 shrink-0 rounded-full border border-border-strong bg-surface transition-colors',
        'data-[state=checked]:border-primary',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      <RadioGroupPrimitive.Indicator className="flex items-center justify-center">
        <span aria-hidden="true" className="block size-2 rounded-full bg-primary" />
      </RadioGroupPrimitive.Indicator>
    </RadioGroupPrimitive.Item>
  );
});

/** Label + description row, the shape every radio list in this product uses. */
export function RadioOption({
  value,
  label,
  description,
  disabled,
}: {
  value: string;
  label: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
}) {
  const id = React.useId();
  return (
    <div className="flex items-start gap-2.5">
      <RadioGroupItem id={id} value={value} disabled={disabled} className="mt-0.5" />
      <div className="grid gap-0.5 leading-tight">
        <label htmlFor={id} className="cursor-pointer text-sm font-medium text-text">
          {label}
        </label>
        {description ? <p className="text-xs text-text-muted">{description}</p> : null}
      </div>
    </div>
  );
}
