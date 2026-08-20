'use client';

import * as React from 'react';
import { AlertCircle } from 'lucide-react';

import { cn, nextId } from '@/lib/utils';
import { Label } from './label';

/**
 * Wires label / hint / error to a single control.
 *
 * The whole point is that consumers cannot forget `aria-describedby`: the field
 * clones its child and injects `id`, `aria-describedby` and `aria-invalid`.
 * Hand-wiring these is where forms silently lose their accessibility.
 */

export interface FormFieldProps {
  label: React.ReactNode;
  /** Supplied when the control is externally controlled; otherwise generated. */
  htmlFor?: string;
  hint?: React.ReactNode;
  error?: string | null;
  required?: boolean;
  className?: string;
  /** Layout escape hatch for wide forms. */
  labelSuffix?: React.ReactNode;
  children: React.ReactElement<{
    id?: string;
    'aria-describedby'?: string;
    'aria-invalid'?: boolean;
    'aria-required'?: boolean;
  }>;
}

export function FormField({
  label,
  htmlFor,
  hint,
  error,
  required,
  className,
  labelSuffix,
  children,
}: FormFieldProps) {
  const reactId = React.useId();
  const controlId = htmlFor ?? children.props.id ?? `field-${reactId}`;
  const hintId = hint ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;

  const control = React.cloneElement(children, {
    id: controlId,
    'aria-describedby': describedBy,
    'aria-invalid': error ? true : undefined,
    'aria-required': required || undefined,
  });

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div className="flex items-baseline justify-between gap-2">
        <Label htmlFor={controlId} required={required}>
          {label}
        </Label>
        {labelSuffix}
      </div>
      {control}
      {hint && !error ? (
        <p id={hintId} className="text-xs leading-relaxed text-text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        // role="alert" so the message is announced when validation fails after
        // submit, not only when focus happens to land on the field.
        <p id={errorId} role="alert" className="flex items-start gap-1.5 text-xs text-danger">
          <AlertCircle aria-hidden="true" className="mt-px size-3.5 shrink-0" />
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}

export { nextId };
