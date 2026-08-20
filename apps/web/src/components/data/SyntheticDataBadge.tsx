'use client';

import { FlaskConical } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Tooltip } from '@/components/ui/tooltip';

/**
 * plan.md §11: when a tenant is in synthetic mode, every screen that shows a
 * number must say so. The failure this prevents is a screenshot of generated
 * data ending up in a board deck, and nothing on the image saying it was
 * generated. That is why the badge is part of `PageHeader` rather than something
 * a page opts into.
 */

export interface SyntheticDataBadgeProps {
  /** Usually `session.activeTenant?.syntheticMode`. Renders nothing when false. */
  active: boolean | null | undefined;
  className?: string;
  size?: 'sm' | 'md';
}

export function SyntheticDataBadge({ active, className, size = 'sm' }: SyntheticDataBadgeProps) {
  if (!active) return null;

  return (
    <Tooltip
      content="This tenant is running on generated data. Figures are structurally realistic but describe no real prescriber, event or spend, and must not be quoted externally."
    >
      <span>
        <Badge variant="warning" size={size} className={className}>
          <FlaskConical aria-hidden="true" />
          Synthetic data
        </Badge>
      </span>
    </Tooltip>
  );
}
