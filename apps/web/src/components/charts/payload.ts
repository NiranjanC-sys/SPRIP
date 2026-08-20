import type { ChartPayload } from '@/lib/api/types';
import {
  EM_DASH,
  formatCompact,
  formatCurrency,
  formatCurrencyCompact,
  formatDecimal,
  formatInteger,
  formatMultiple,
  formatPercent,
  formatSignedPercent,
} from '@/lib/formatters';
import type { ChartTableData } from './Chart';
import { seriesColor, type ChartTheme } from './chartTheme';

/** The subset of formatters whose signature is `(value: number) => string`. */
const NUMERIC_FORMATTERS = {
  integer: formatInteger,
  decimal: formatDecimal,
  currency: formatCurrency,
  currencyCompact: formatCurrencyCompact,
  compact: formatCompact,
  percent: formatPercent,
  signedPercent: formatSignedPercent,
  multiple: formatMultiple,
} as const;

export type NumericFormatterName = keyof typeof NUMERIC_FORMATTERS;

/**
 * Adapters from the API's `ChartPayload` to the two shapes the Chart wrapper
 * needs. Kept out of `Chart.tsx` so the wrapper stays payload-agnostic — a
 * dashboard with a bespoke shape can build its own option and still get the
 * theming, resize and table behaviour.
 */

/**
 * The accessible table alternative. Nulls become an em dash rather than `0`:
 * "no reported prescriptions this month" and "zero prescriptions" are different
 * claims, and conflating them is exactly the kind of quiet misstatement this
 * product exists to avoid.
 */
export function chartPayloadToTable(
  payload: ChartPayload,
  options: { formatter?: NumericFormatterName; caption?: string; categoryHeader?: string } = {},
): ChartTableData {
  const { formatter = 'decimal', caption, categoryHeader = 'Period' } = options;
  const format = NUMERIC_FORMATTERS[formatter];

  return {
    caption,
    columns: [categoryHeader, ...payload.series.map((s) => s.label)],
    rows: payload.categories.map((category, index) => [
      category,
      ...payload.series.map((s) => {
        const value = s.values[index];
        return value === null || value === undefined ? EM_DASH : format(value);
      }),
    ]),
  };
}

export interface SeriesOptions {
  type?: 'line' | 'bar';
  /** Renders `lower`/`upper` as a shaded band behind the attendee series. */
  showBands?: boolean;
  smooth?: boolean;
  stack?: string;
}

/**
 * Builds ECharts series objects with the fixed cohort colours applied.
 *
 * Confidence bands are drawn as a transparent lower line plus a stacked filled
 * area — the standard ECharts idiom, since it has no first-class band series.
 * They are emitted before the value series so the fill sits behind the line.
 */
export function chartPayloadToSeries(
  payload: ChartPayload,
  theme: ChartTheme,
  options: SeriesOptions = {},
): unknown[] {
  const { type = 'line', showBands = false, smooth = true, stack } = options;
  const out: unknown[] = [];

  payload.series.forEach((series, index) => {
    const color = seriesColor(theme, series.role, index);

    if (showBands && series.lower && series.upper) {
      out.push(
        {
          name: `${series.label} lower bound`,
          type: 'line',
          data: series.lower,
          lineStyle: { opacity: 0 },
          symbol: 'none',
          stack: `band-${series.key}`,
          silent: true,
          // Excluded from the legend: a reader toggles "Attendee", not
          // "Attendee lower bound".
          legendHoverLink: false,
          tooltip: { show: false },
        },
        {
          name: `${series.label} interval`,
          type: 'line',
          data: series.upper.map((upper, i) => {
            const lower = series.lower?.[i];
            return upper === null || lower === null || lower === undefined ? null : upper - lower;
          }),
          lineStyle: { opacity: 0 },
          symbol: 'none',
          stack: `band-${series.key}`,
          areaStyle: { color, opacity: theme.bandOpacity },
          silent: true,
          legendHoverLink: false,
          tooltip: { show: false },
        },
      );
    }

    out.push({
      name: series.label,
      type,
      data: series.values,
      smooth: type === 'line' ? smooth : undefined,
      stack,
      symbol: 'circle',
      symbolSize: 5,
      showSymbol: false,
      // A dashed control line so the two cohorts remain distinguishable in
      // greyscale and to a reader with a colour vision deficiency.
      lineStyle: {
        width: 2,
        color,
        type: series.role === 'control' ? ('dashed' as const) : ('solid' as const),
      },
      itemStyle: { color },
      connectNulls: false,
      emphasis: { focus: 'series' as const },
    });
  });

  return out;
}
