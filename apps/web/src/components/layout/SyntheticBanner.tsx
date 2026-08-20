import { FlaskConical } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * The synthetic-tenant banner.
 *
 * plan.md §11. There is deliberately **no dismiss control**, and that is the
 * whole design: a demo tenant's numbers are structurally realistic, and the only
 * thing standing between a screenshot of generated data and a slide captioned
 * "our Q3 results" is a marking that cannot be turned off. A banner the user can
 * close is a banner that is closed in every screenshot that matters.
 *
 * It sits above the top bar rather than inside the page body so it survives
 * scrolling and appears on every route, including error and empty states.
 */

export function SyntheticBanner({
  environmentLabel,
  className,
}: {
  /** e.g. "Demo" or "Staging". Rendered when the deployment is not production. */
  environmentLabel?: string | null;
  className?: string;
}) {
  return (
    <div
      role="note"
      aria-label="Synthetic data notice"
      className={cn(
        'flex items-center justify-center gap-2 bg-warning px-4 py-1.5 text-center text-xs font-medium text-canvas',
        className,
      )}
    >
      <FlaskConical aria-hidden="true" className="size-3.5 shrink-0" />
      <span>
        Synthetic data
        {environmentLabel ? ` · ${environmentLabel}` : ''} — figures describe no real prescriber,
        event or spend and must not be reported externally.
      </span>
    </div>
  );
}
