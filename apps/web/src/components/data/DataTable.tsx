'use client';

import * as React from 'react';
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
  type Table as TanstackTable,
  type VisibilityState,
} from '@tanstack/react-table';
import { ArrowDown, ArrowUp, ArrowUpDown, Download, Search, Settings2 } from 'lucide-react';

import { cn, debounce } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { IconButton } from '@/components/ui/icon-button';
import { Input } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  type Density,
} from '@/components/ui/table';
import { EmptyState, ErrorState, ForbiddenState } from './states';

/**
 * Server-driven table.
 *
 * Sorting, filtering and pagination are the *server's* job here — the client
 * never holds a full result set, so `manualSorting` / `manualPagination` are
 * always on. Doing otherwise would mean sorting page 1 of 40 and presenting it
 * as sorted, which is a subtly wrong answer rather than a slow one.
 *
 * Pagination is cursor-based; see `ui/pagination.tsx` for why.
 */

export interface DataTableProps<TData> {
  columns: ReadonlyArray<ColumnDef<TData, unknown>>;
  data: readonly TData[];
  /** Stable row identity — required for selection to survive a refetch. */
  getRowId: (row: TData, index: number) => string;

  loading?: boolean;
  error?: unknown;
  /** Renders the 403 state instead of the table. */
  forbidden?: boolean;
  onRetry?: () => void;

  /* --- server-driven state ------------------------------------------------ */
  sorting?: SortingState;
  onSortingChange?: (sorting: SortingState) => void;

  globalFilter?: string;
  onGlobalFilterChange?: (value: string) => void;
  searchPlaceholder?: string;

  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
  canPrevious?: boolean;
  canNext?: boolean;
  onPrevious?: () => void;
  onNext?: () => void;
  totalCount?: number | null;

  /* --- selection ---------------------------------------------------------- */
  enableSelection?: boolean;
  rowSelection?: RowSelectionState;
  onRowSelectionChange?: (selection: RowSelectionState) => void;
  /** Rendered above the table when at least one row is selected. */
  bulkActions?: (selectedIds: string[]) => React.ReactNode;

  /* --- presentation ------------------------------------------------------- */
  density?: Density;
  onDensityChange?: (density: Density) => void;
  stickyHeader?: boolean;
  maxHeight?: number | string;
  emptyTitle?: string;
  emptyDescription?: React.ReactNode;
  emptyAction?: React.ReactNode;
  caption?: string;
  onRowClick?: (row: TData) => void;

  /** Given the current rows, produce CSV. The caller owns column semantics. */
  onExport?: () => void;
  exportLabel?: string;

  toolbarSlot?: React.ReactNode;
  className?: string;
}

const SELECT_COLUMN_ID = '__select';

export function DataTable<TData>({
  columns,
  data,
  getRowId,
  loading = false,
  error,
  forbidden = false,
  onRetry,
  sorting,
  onSortingChange,
  globalFilter,
  onGlobalFilterChange,
  searchPlaceholder = 'Search…',
  pageSize = 25,
  onPageSizeChange,
  canPrevious = false,
  canNext = false,
  onPrevious,
  onNext,
  totalCount,
  enableSelection = false,
  rowSelection,
  onRowSelectionChange,
  bulkActions,
  density: densityProp,
  onDensityChange,
  stickyHeader = true,
  maxHeight,
  emptyTitle,
  emptyDescription,
  emptyAction,
  caption,
  onRowClick,
  onExport,
  exportLabel = 'Export CSV',
  toolbarSlot,
  className,
}: DataTableProps<TData>) {
  const [internalDensity, setInternalDensity] = React.useState<Density>('comfortable');
  const density = densityProp ?? internalDensity;
  const setDensity = onDensityChange ?? setInternalDensity;

  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({});
  const [searchDraft, setSearchDraft] = React.useState(globalFilter ?? '');

  // Search hits the server, so it is debounced. 300ms is the point where a
  // typist stops noticing lag but the API stops seeing a request per keystroke.
  const pushSearch = React.useMemo(
    () => debounce((value: string) => onGlobalFilterChange?.(value), 300),
    [onGlobalFilterChange],
  );

  React.useEffect(() => {
    setSearchDraft(globalFilter ?? '');
  }, [globalFilter]);

  const resolvedColumns = React.useMemo<Array<ColumnDef<TData, unknown>>>(() => {
    if (!enableSelection) return [...columns];
    const selectColumn: ColumnDef<TData, unknown> = {
      id: SELECT_COLUMN_ID,
      size: 36,
      enableSorting: false,
      enableHiding: false,
      header: ({ table }) => (
        <Checkbox
          checked={
            table.getIsAllPageRowsSelected()
              ? true
              : table.getIsSomePageRowsSelected()
                ? 'indeterminate'
                : false
          }
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(value === true)}
          aria-label="Select all rows on this page"
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(value === true)}
          aria-label="Select row"
          onClick={(e) => e.stopPropagation()}
        />
      ),
    };
    return [selectColumn, ...columns];
  }, [columns, enableSelection]);

  const table = useReactTable<TData>({
    data: data as TData[],
    columns: resolvedColumns,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    // Every list in this product is server-ranked; see the note above.
    manualSorting: true,
    manualPagination: true,
    manualFiltering: true,
    enableRowSelection: enableSelection,
    state: {
      ...(sorting ? { sorting } : {}),
      ...(rowSelection ? { rowSelection } : {}),
      columnVisibility,
    },
    onSortingChange: (updater) => {
      if (!onSortingChange) return;
      onSortingChange(typeof updater === 'function' ? updater(sorting ?? []) : updater);
    },
    onRowSelectionChange: (updater) => {
      if (!onRowSelectionChange) return;
      onRowSelectionChange(typeof updater === 'function' ? updater(rowSelection ?? {}) : updater);
    },
    onColumnVisibilityChange: setColumnVisibility,
  });

  const selectedIds = React.useMemo(
    () => Object.entries(rowSelection ?? {}).filter(([, v]) => v).map(([k]) => k),
    [rowSelection],
  );

  const hasToolbar = Boolean(onGlobalFilterChange || onExport || toolbarSlot || onDensityChange !== undefined);

  return (
    <div className={cn('flex flex-col rounded-lg border border-border bg-surface', className)}>
      {hasToolbar ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-2.5">
          {onGlobalFilterChange ? (
            <Input
              value={searchDraft}
              onChange={(e) => {
                setSearchDraft(e.target.value);
                pushSearch(e.target.value);
              }}
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
              iconLeft={<Search />}
              className="h-8 w-56 text-xs"
            />
          ) : null}

          {toolbarSlot}

          <div className="ml-auto flex items-center gap-1.5">
            {onExport ? (
              <Button size="sm" variant="secondary" onClick={onExport} iconLeft={<Download />}>
                {exportLabel}
              </Button>
            ) : null}

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <IconButton label="Table options" size="sm" variant="secondary">
                  <Settings2 />
                </IconButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuLabel>Density</DropdownMenuLabel>
                <DropdownMenuRadioGroup
                  value={density}
                  onValueChange={(v) => setDensity(v as Density)}
                >
                  <DropdownMenuRadioItem value="comfortable">Comfortable</DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="compact">Compact</DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>Columns</DropdownMenuLabel>
                {table
                  .getAllLeafColumns()
                  .filter((column) => column.getCanHide() && column.id !== SELECT_COLUMN_ID)
                  .map((column) => (
                    <DropdownMenuCheckboxItem
                      key={column.id}
                      checked={column.getIsVisible()}
                      onCheckedChange={(value) => column.toggleVisibility(Boolean(value))}
                      onSelect={(e) => e.preventDefault()}
                    >
                      {columnLabel(column.id, table)}
                    </DropdownMenuCheckboxItem>
                  ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      ) : null}

      {enableSelection && selectedIds.length > 0 && bulkActions ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-primary/8 px-3 py-2">
          <span className="text-xs font-medium text-text">
            {selectedIds.length} selected
          </span>
          <div className="ml-auto flex items-center gap-1.5">{bulkActions(selectedIds)}</div>
        </div>
      ) : null}

      <div
        className={cn('scroll-thin min-h-0 overflow-auto', maxHeight ? '' : 'max-h-[calc(100vh-22rem)]')}
        style={maxHeight ? { maxHeight } : undefined}
      >
        {forbidden ? (
          <ForbiddenState compact />
        ) : error ? (
          <ErrorState error={error} onRetry={onRetry} compact />
        ) : (
          <Table>
            {caption ? <caption className="sr-only">{caption}</caption> : null}
            <TableHeader sticky={stickyHeader}>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    const canSort = header.column.getCanSort() && Boolean(onSortingChange);
                    const sorted = header.column.getIsSorted();
                    const numeric = Boolean(header.column.columnDef.meta && (header.column.columnDef.meta as { numeric?: boolean }).numeric);

                    return (
                      <TableHead
                        key={header.id}
                        density={density}
                        numeric={numeric}
                        style={header.getSize() ? { width: header.getSize() } : undefined}
                        aria-sort={
                          sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : undefined
                        }
                      >
                        {header.isPlaceholder ? null : canSort ? (
                          <button
                            type="button"
                            onClick={header.column.getToggleSortingHandler()}
                            className={cn(
                              'inline-flex items-center gap-1 rounded-sm uppercase tracking-wide hover:text-text',
                              numeric && 'flex-row-reverse',
                            )}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sorted === 'asc' ? (
                              <ArrowUp aria-hidden="true" className="size-3" />
                            ) : sorted === 'desc' ? (
                              <ArrowDown aria-hidden="true" className="size-3" />
                            ) : (
                              <ArrowUpDown aria-hidden="true" className="size-3 opacity-40" />
                            )}
                          </button>
                        ) : (
                          flexRender(header.column.columnDef.header, header.getContext())
                        )}
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>

            <TableBody>
              {loading ? (
                <LoadingRows columnCount={resolvedColumns.length} density={density} />
              ) : table.getRowModel().rows.length === 0 ? (
                <tr>
                  <td colSpan={resolvedColumns.length}>
                    <EmptyState compact title={emptyTitle} description={emptyDescription} />
                    {emptyAction ? <div className="pb-8 text-center">{emptyAction}</div> : null}
                  </td>
                </tr>
              ) : (
                table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    selected={row.getIsSelected()}
                    onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                    className={onRowClick ? 'cursor-pointer' : undefined}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        density={density}
                        numeric={Boolean(
                          cell.column.columnDef.meta &&
                            (cell.column.columnDef.meta as { numeric?: boolean }).numeric,
                        )}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </div>

      {onPrevious && onNext ? (
        <Pagination
          pageSize={pageSize}
          onPageSizeChange={onPageSizeChange}
          rowCount={data.length}
          totalCount={totalCount ?? null}
          canPrevious={canPrevious}
          canNext={canNext}
          onPrevious={onPrevious}
          onNext={onNext}
          disabled={loading}
        />
      ) : null}
    </div>
  );
}

function LoadingRows({ columnCount, density }: { columnCount: number; density: Density }) {
  return (
    <>
      {Array.from({ length: 6 }, (_, rowIndex) => (
        <TableRow key={rowIndex}>
          {Array.from({ length: columnCount }, (_, cellIndex) => (
            <TableCell key={cellIndex} density={density}>
              <Skeleton
                className="h-3.5"
                style={{ width: `${45 + ((rowIndex * 7 + cellIndex * 13) % 40)}%` }}
                label={rowIndex === 0 && cellIndex === 0 ? 'Loading rows' : undefined}
              />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

/** Best-effort human label for the column-visibility menu. */
function columnLabel<TData>(columnId: string, table: TanstackTable<TData>): string {
  const column = table.getColumn(columnId);
  const meta = column?.columnDef.meta as { label?: string } | undefined;
  if (meta?.label) return meta.label;
  const header = column?.columnDef.header;
  if (typeof header === 'string') return header;
  return columnId;
}

export type { ColumnDef, RowSelectionState, SortingState };
