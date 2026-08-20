import { cn } from '@/lib/utils';

/**
 * Unstyled-but-themed table primitives.
 *
 * `DataTable` composes these for the server-driven case; they are also exported
 * on their own for the small static tables (a chart's "view as table"
 * alternative, a definition list of gate results) where a full TanStack instance
 * would be overkill.
 */

export type Density = 'comfortable' | 'compact';

const CELL_PAD: Record<Density, string> = {
  comfortable: 'px-3 py-2.5',
  compact: 'px-2.5 py-1.5',
};

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return <table className={cn('w-full caption-bottom border-collapse text-sm', className)} {...props} />;
}

export function TableHeader({ className, sticky, ...props }: React.HTMLAttributes<HTMLTableSectionElement> & { sticky?: boolean }) {
  return (
    <thead
      className={cn(
        '[&_tr]:border-b [&_tr]:border-border',
        // Sticky headers need an opaque background or rows show through as they
        // scroll under. `bg-surface` is that background, not decoration.
        sticky && 'sticky top-0 z-10 bg-surface',
        className,
      )}
      {...props}
    />
  );
}

export function TableBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('[&_tr:last-child]:border-0', className)} {...props} />;
}

export function TableFooter({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <tfoot
      className={cn('border-t border-border bg-surface-sunken font-medium [&>tr]:last:border-b-0', className)}
      {...props}
    />
  );
}

export function TableRow({
  className,
  selected,
  ...props
}: React.HTMLAttributes<HTMLTableRowElement> & { selected?: boolean }) {
  return (
    <tr
      data-state={selected ? 'selected' : undefined}
      className={cn(
        'border-b border-border transition-colors hover:bg-surface-sunken/60',
        selected && 'bg-primary/8',
        className,
      )}
      {...props}
    />
  );
}

export interface TableHeadProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean;
  density?: Density;
}

export function TableHead({ className, numeric, density = 'comfortable', ...props }: TableHeadProps) {
  return (
    <th
      scope="col"
      className={cn(
        'text-2xs font-semibold uppercase tracking-wide text-text-subtle',
        CELL_PAD[density],
        numeric ? 'text-right' : 'text-left',
        className,
      )}
      {...props}
    />
  );
}

export interface TableCellProps extends React.TdHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean;
  density?: Density;
}

export function TableCell({ className, numeric, density = 'comfortable', ...props }: TableCellProps) {
  return (
    <td
      className={cn(
        'align-middle text-text',
        CELL_PAD[density],
        // Right-aligned tabular figures: the only way a column of currency
        // reads as a column rather than as ragged text.
        numeric && 'text-right font-mono text-xs tabular-nums',
        className,
      )}
      {...props}
    />
  );
}

export function TableCaption({ className, ...props }: React.HTMLAttributes<HTMLTableCaptionElement>) {
  return <caption className={cn('mt-3 text-xs text-text-muted', className)} {...props} />;
}
