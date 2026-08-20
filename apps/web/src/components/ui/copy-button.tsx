'use client';

import * as React from 'react';
import { Check, Copy } from 'lucide-react';

import { IconButton, type IconButtonProps } from './icon-button';

export interface CopyButtonProps extends Omit<IconButtonProps, 'label' | 'children' | 'onClick'> {
  value: string;
  label?: string;
  /** Announced after a successful copy. */
  copiedLabel?: string;
}

/**
 * Copies a lineage tuple, a run ID, a request ID. `navigator.clipboard` is not
 * available on insecure origins or in some embedded browsers, so the failure
 * path leaves the icon unchanged rather than lying with a checkmark.
 */
export function CopyButton({
  value,
  label = 'Copy',
  copiedLabel = 'Copied',
  size = 'sm',
  ...props
}: CopyButtonProps) {
  const [copied, setCopied] = React.useState(false);
  const timer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  React.useEffect(() => () => clearTimeout(timer.current), []);

  const onCopy = React.useCallback(() => {
    void navigator.clipboard?.writeText(value).then(
      () => {
        setCopied(true);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), 1600);
      },
      () => {
        /* Clipboard unavailable — leave the affordance honest. */
      },
    );
  }, [value]);

  return (
    <IconButton {...props} size={size} label={copied ? copiedLabel : label} onClick={onCopy}>
      {copied ? <Check className="text-positive" /> : <Copy />}
    </IconButton>
  );
}
