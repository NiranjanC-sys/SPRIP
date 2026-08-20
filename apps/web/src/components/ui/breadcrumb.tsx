import Link from 'next/link';
import { ChevronRight } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface Crumb {
  label: string;
  href?: string;
}

/**
 * `aria-current="page"` on the last item, `<nav aria-label="Breadcrumb">` on the
 * wrapper — the pattern AT actually recognises. Separators are `aria-hidden`
 * because "chevron right" read aloud between every level is noise.
 */
export function Breadcrumb({ items, className }: { items: readonly Crumb[]; className?: string }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="Breadcrumb" className={cn('min-w-0', className)}>
      <ol className="flex min-w-0 flex-wrap items-center gap-1 text-xs text-text-muted">
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`} className="flex min-w-0 items-center gap-1">
              {item.href && !isLast ? (
                <Link href={item.href} className="truncate rounded-sm hover:text-text hover:underline">
                  {item.label}
                </Link>
              ) : (
                <span className="truncate text-text" aria-current={isLast ? 'page' : undefined}>
                  {item.label}
                </span>
              )}
              {isLast ? null : <ChevronRight aria-hidden="true" className="size-3 shrink-0 text-text-subtle" />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
