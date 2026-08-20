'use client';

import * as React from 'react';
import * as echarts from 'echarts/core';
import { BarChart, HeatmapChart, LineChart, PieChart, ScatterChart } from 'echarts/charts';
import {
  DatasetComponent,
  GraphicComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { ChevronDown, Table2 } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { baseChartOption, useChartTheme, type ChartTheme } from './chartTheme';

/**
 * The only place ECharts is instantiated.
 *
 * Responsibilities, in the order they matter:
 *  1. Rebuild the option whenever the theme tokens change, so the light/dark
 *     toggle repaints charts in place rather than after a reload.
 *  2. Observe the container and resize — a chart inside a collapsing sidebar or
 *     a tab panel is otherwise permanently the wrong width.
 *  3. Provide a real `<table>` alternative. A canvas is opaque to assistive
 *     technology; plan.md §7.0's WCAG 2.1 AA bar cannot be met by an alt string.
 *  4. Never own data. `buildOption` receives the theme and returns an option
 *     built from props the caller got from the API. There are no numbers in
 *     this file, and `npm run check:no-magic-charts` keeps it that way.
 */

// Tree-shaken registration: importing 'echarts' wholesale pulls ~1MB, most of it
// map and graph charts this product has no use for.
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DatasetComponent,
  VisualMapComponent,
  MarkLineComponent,
  MarkAreaComponent,
  GraphicComponent,
  CanvasRenderer,
]);

export type EChartsOption = Parameters<echarts.ECharts['setOption']>[0];

export interface ChartTableData {
  caption?: string;
  columns: readonly string[];
  /** Pre-formatted strings. Formatting is the caller's job — it owns the units. */
  rows: ReadonlyArray<readonly string[]>;
}

export interface ChartProps {
  /**
   * Builds the ECharts option from the live theme. A function rather than an
   * object so colours cannot be captured once and go stale on theme change.
   */
  buildOption: (theme: ChartTheme) => EChartsOption;
  /** Required: the accessible name of the figure. */
  ariaLabel: string;
  /** One or two sentences describing the trend, for the figure's description. */
  description?: string;
  /** Tabular equivalent. Strongly recommended; without it the chart is opaque to AT. */
  table?: ChartTableData;
  height?: number;
  className?: string;
  loading?: boolean;
  /** Passed straight to `setOption`. Set true when the series count changes. */
  notMerge?: boolean;
  onEvents?: Readonly<Record<string, (params: unknown) => void>>;
  /** Hides the "View as table" disclosure when the caller renders its own. */
  hideTableToggle?: boolean;
}

export function Chart({
  buildOption,
  ariaLabel,
  description,
  table,
  height = 280,
  className,
  loading = false,
  notMerge = false,
  onEvents,
  hideTableToggle = false,
}: ChartProps) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const instanceRef = React.useRef<echarts.ECharts | null>(null);
  const theme = useChartTheme();
  const [showTable, setShowTable] = React.useState(false);
  const descriptionId = React.useId();

  // Keep the latest builder/handlers in refs so the init effect does not have to
  // list them as dependencies and tear the chart down on every parent render.
  const buildRef = React.useRef(buildOption);
  buildRef.current = buildOption;
  const eventsRef = React.useRef(onEvents);
  eventsRef.current = onEvents;

  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = echarts.init(el, undefined, { renderer: 'canvas' });
    instanceRef.current = chart;

    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(el);

    return () => {
      observer.disconnect();
      chart.dispose();
      instanceRef.current = null;
    };
  }, []);

  // Option updates: theme changes and data changes both land here.
  React.useEffect(() => {
    const chart = instanceRef.current;
    if (!chart || theme.mode === undefined) return;
    const option = buildRef.current(theme);
    chart.setOption({ ...baseChartOption(theme), ...(option as object) }, { notMerge });
  }, [theme, buildOption, notMerge]);

  React.useEffect(() => {
    const chart = instanceRef.current;
    const handlers = eventsRef.current;
    if (!chart || !handlers) return;
    for (const [name, handler] of Object.entries(handlers)) chart.on(name, handler);
    return () => {
      for (const name of Object.keys(handlers)) chart.off(name);
    };
  }, [onEvents]);

  React.useEffect(() => {
    if (loading) instanceRef.current?.showLoading('default', { showSpinner: false, maskColor: 'transparent' });
    else instanceRef.current?.hideLoading();
  }, [loading]);

  if (loading) {
    return <Skeleton className={cn('w-full', className)} style={{ height }} label={`${ariaLabel} loading`} />;
  }

  return (
    <figure className={cn('flex flex-col gap-2', className)}>
      <div
        ref={containerRef}
        role="img"
        aria-label={ariaLabel}
        aria-describedby={description ? descriptionId : undefined}
        style={{ height }}
        className="w-full"
      />

      {description ? (
        <figcaption id={descriptionId} className="text-xs leading-relaxed text-text-muted">
          {description}
        </figcaption>
      ) : null}

      {table && !hideTableToggle ? (
        <div>
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            aria-expanded={showTable}
            className="inline-flex items-center gap-1.5 rounded-sm text-xs font-medium text-text-muted hover:text-text"
          >
            <Table2 aria-hidden="true" className="size-3.5" />
            View as table
            <ChevronDown
              aria-hidden="true"
              className={cn('size-3.5 transition-transform', showTable && 'rotate-180')}
            />
          </button>

          {showTable ? (
            <div className="scroll-thin mt-2 max-h-80 overflow-auto rounded-md border border-border">
              <ChartDataTable data={table} label={ariaLabel} />
            </div>
          ) : null}
        </div>
      ) : null}
    </figure>
  );
}

function ChartDataTable({ data, label }: { data: ChartTableData; label: string }) {
  return (
    <Table>
      <TableCaption className="sr-only">{data.caption ?? `${label} — data table`}</TableCaption>
      <TableHeader sticky>
        <TableRow>
          {data.columns.map((column, i) => (
            <TableHead key={column} density="compact" numeric={i > 0}>
              {column}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.rows.map((row, rowIndex) => (
          <TableRow key={rowIndex}>
            {row.map((cell, cellIndex) => (
              <TableCell key={cellIndex} density="compact" numeric={cellIndex > 0}>
                {cell}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
