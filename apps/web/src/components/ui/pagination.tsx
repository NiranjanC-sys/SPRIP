'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';

import { cn } from '@/lib/utils';
import { formatInteger } from '@/lib/formatters';
import { Button } from './button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './select';

/**
 * Cursor pagination, not page numbers.
 *
 * Analytical lists re-rank between requests — a new data version lands and the
 * event ranked 41st is now 38th — so an offset would silently skip or duplicate
 * rows. The API returns an opaque `nextCursor`; the UI can only go forward and
 * back through cursors it has already seen, which is why "page 7" is not
 * offered. `totalCount` is shown when the server can afford to compute it.
 */

export interface PaginationProps {
  pageSize: number;
  onPageSizeChange?: (size: number) => void;
  pageSizeOptions?: readonly number[];
  /** Number of rows on the current page. */
  rowCount: number;
  /** Total across all pages, when known. */
  totalCount?: number | null;
  canPrevious: boolean;
  canNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
  /** 1-based, for the "page N" affordance. */
  pageIndex?: number;
  className?: string;
  disabled?: boolean;
}

export function Pagination({
  pageSize,
  onPageSizeChange,
  pageSizeOptions = [25, 50, 100],
  rowCount,
  totalCount,
  canPrevious,
  canNext,
  onPrevious,
  onNext,
  pageIndex,
  className,
  disabled,
}: PaginationProps) {
  return (
    <nav
      aria-label="Pagination"
      className={cn(
        'flex flex-wrap items-center justify-between gap-3 border-t border-border px-3 py-2',
        className,
      )}
    >
      <p className="text-xs text-text-muted" aria-live="polite">
        {totalCount == null
          ? `Showing ${formatInteger(rowCount)} rows`
          : `Showing ${formatInteger(rowCount)} of ${formatInteger(totalCount)} rows`}
        {pageIndex ? ` · page ${formatInteger(pageIndex)}` : ''}
      </p>

      <div className="flex items-center gap-3">
        {onPageSizeChange ? (
          <label className="flex items-center gap-2 text-xs text-text-muted">
            <span>Rows</span>
            <Select
              value={String(pageSize)}
              onValueChange={(v) => onPageSizeChange(Number(v))}
              disabled={disabled}
            >
              <SelectTrigger size="sm" className="w-20">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {pageSizeOptions.map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        ) : null}

        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="secondary"
            onClick={onPrevious}
            disabled={disabled || !canPrevious}
            iconLeft={<ChevronLeft />}
          >
            Previous
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={onNext}
            disabled={disabled || !canNext}
            iconRight={<ChevronRight />}
          >
            Next
          </Button>
        </div>
      </div>
    </nav>
  );
}
