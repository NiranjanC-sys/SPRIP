import Link from 'next/link';

import { cn } from '@/lib/utils';

/**
 * The product mark.
 *
 * Drawn in SVG with `currentColor` rather than shipped as an image so it inherits
 * the nav foreground and needs no second asset for dark mode. The glyph is the
 * product's own idea in miniature: two trajectories that separate after a shared
 * point — an attendee cohort and its counterfactual diverging at the event.
 */

export function ProductMark({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <Link
      href="/"
      className={cn(
        'flex min-w-0 items-center gap-2 rounded-md text-nav-fg-active outline-offset-2',
        collapsed && 'justify-center',
      )}
    >
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="size-6 shrink-0"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="0.75" y="0.75" width="22.5" height="22.5" rx="6" className="fill-primary" />
        <path d="M4.5 16.5 L9 12 L13 14" stroke="currentColor" strokeWidth="1.75" opacity="0.55" />
        <path d="M13 14 L15.5 15.5 L19.5 15" stroke="currentColor" strokeWidth="1.75" opacity="0.55" />
        <path d="M13 14 L16 9.5 L19.5 5.5" stroke="currentColor" strokeWidth="2" />
        <circle cx="13" cy="14" r="1.9" fill="currentColor" />
      </svg>
      {collapsed ? (
        <span className="sr-only">Speaker ROI — home</span>
      ) : (
        <span className="flex min-w-0 flex-col leading-none">
          <span className="truncate text-sm font-semibold tracking-tight">Speaker ROI</span>
          <span className="truncate text-2xs text-nav-fg">Impact &amp; investment</span>
        </span>
      )}
    </Link>
  );
}
