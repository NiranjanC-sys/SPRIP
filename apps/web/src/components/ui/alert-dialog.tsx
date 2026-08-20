'use client';

import * as React from 'react';
import * as AlertDialogPrimitive from '@radix-ui/react-alert-dialog';
import { AlertTriangle } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from './button';
import { FormField } from './form-field';
import { Textarea } from './textarea';

export const AlertDialog = AlertDialogPrimitive.Root;
export const AlertDialogTrigger = AlertDialogPrimitive.Trigger;

export interface ConfirmDialogProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: string;
  description: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'danger' | 'primary';
  /**
   * plan.md §7.0: destructive and state-changing actions require a confirmation
   * *and* an audit note. When true the note is mandatory and Confirm stays
   * disabled until it is written — the note is what an auditor reads six months
   * later, so an empty one is worse than no dialog at all.
   */
  requireNote?: boolean;
  noteLabel?: string;
  notePlaceholder?: string;
  loading?: boolean;
  onConfirm: (note: string) => void;
  children?: React.ReactNode;
}

/**
 * Destructive-confirmation dialog. `AlertDialog` (not `Dialog`) because it must
 * trap focus on the cancel action and cannot be dismissed by clicking outside —
 * withdrawing a published result is not an accidental click.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  tone = 'danger',
  requireNote = false,
  noteLabel = 'Reason for this change',
  notePlaceholder = 'Recorded in the audit trail.',
  loading = false,
  onConfirm,
  children,
}: ConfirmDialogProps) {
  const [note, setNote] = React.useState('');
  const canConfirm = !requireNote || note.trim().length >= 4;

  return (
    <AlertDialogPrimitive.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) setNote('');
        onOpenChange?.(next);
      }}
    >
      {children ? <AlertDialogPrimitive.Trigger asChild>{children}</AlertDialogPrimitive.Trigger> : null}
      <AlertDialogPrimitive.Portal>
        <AlertDialogPrimitive.Overlay className="fixed inset-0 z-50 bg-overlay backdrop-blur-[2px]" />
        <AlertDialogPrimitive.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2',
            'rounded-lg border border-border bg-surface-raised p-4 shadow-lg',
          )}
        >
          <div className="flex gap-3">
            <span
              aria-hidden="true"
              className={cn(
                'mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full',
                tone === 'danger' ? 'bg-danger-soft text-danger' : 'bg-info-soft text-info',
              )}
            >
              <AlertTriangle className="size-4" />
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <AlertDialogPrimitive.Title className="text-base font-semibold leading-tight text-text">
                {title}
              </AlertDialogPrimitive.Title>
              <AlertDialogPrimitive.Description asChild>
                <div className="text-sm leading-relaxed text-text-muted">{description}</div>
              </AlertDialogPrimitive.Description>
            </div>
          </div>

          {requireNote ? (
            <div className="mt-4">
              <FormField
                label={noteLabel}
                required
                hint="Stored with your user ID and timestamp on the audit record."
              >
                <Textarea
                  rows={3}
                  value={note}
                  placeholder={notePlaceholder}
                  onChange={(e) => setNote(e.target.value)}
                />
              </FormField>
            </div>
          ) : null}

          <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <AlertDialogPrimitive.Cancel asChild>
              <Button variant="secondary" disabled={loading}>
                {cancelLabel}
              </Button>
            </AlertDialogPrimitive.Cancel>
            <Button
              variant={tone === 'danger' ? 'danger' : 'primary'}
              disabled={!canConfirm}
              loading={loading}
              onClick={() => onConfirm(note.trim())}
            >
              {confirmLabel}
            </Button>
          </div>
        </AlertDialogPrimitive.Content>
      </AlertDialogPrimitive.Portal>
    </AlertDialogPrimitive.Root>
  );
}
