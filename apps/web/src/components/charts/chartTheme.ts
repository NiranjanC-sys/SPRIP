'use client';

import * as React from 'react';
import { useTheme } from 'next-themes';

/**
 * ECharts theme derived from CSS custom properties.
 *
 * The tokens live in `globals.css` and nowhere else (plan.md §7.0: no component
 * may hard-code a hex). Reading them back through `getComputedStyle` at runtime
 * is what lets the theme toggle repaint every chart without a reload and without
 * a second, drifting copy of the palette in TypeScript.
 *
 * The read happens once per theme change, not per render — `getComputedStyle` on
 * ~30 variables is cheap but not free, and a dashboard mounts a dozen charts.
 */

export interface ChartTheme {
  /** 'light' | 'dark' — resolved, never 'system'. */
  mode: 'light' | 'dark';
  text: string;
  textMuted: string;
  textSubtle: string;
  surface: string;
  surfaceRaised: string;
  border: string;
  grid: string;
  axis: string;
  /** Fixed roles. Attendee is always the brand blue, control always the grey. */
  attendee: string;
  control: string;
  /** Confidence band fill for the attendee series. */
  band: string;
  bandOpacity: number;
  positive: string;
  warning: string;
  danger: string;
  info: string;
  primary: string;
  /** Categorical palette, in assignment order. */
  categorical: string[];
  /** 5-stop sequential ramp, light → dark. */
  sequential: string[];
  /** 7-stop diverging ramp, teal → neutral → red. */
  diverging: string[];
  fontFamily: string;
  fontMono: string;
}

const CATEGORICAL_KEYS = [
  '--chart-cat-1',
  '--chart-cat-2',
  '--chart-cat-3',
  '--chart-cat-4',
  '--chart-cat-5',
  '--chart-cat-6',
  '--chart-cat-7',
  '--chart-cat-8',
] as const;

const SEQUENTIAL_KEYS = [
  '--chart-seq-1',
  '--chart-seq-2',
  '--chart-seq-3',
  '--chart-seq-4',
  '--chart-seq-5',
] as const;

const DIVERGING_KEYS = [
  '--chart-div-1',
  '--chart-div-2',
  '--chart-div-3',
  '--chart-div-4',
  '--chart-div-5',
  '--chart-div-6',
  '--chart-div-7',
] as const;

/**
 * SSR fallback. Values are structurally valid but deliberately neutral — a chart
 * never renders on the server (ECharts needs a DOM), so this only exists so the
 * hook has a non-null return before the first effect runs.
 */
const SSR_THEME: ChartTheme = {
  mode: 'light',
  text: 'currentColor',
  textMuted: 'currentColor',
  textSubtle: 'currentColor',
  surface: 'transparent',
  surfaceRaised: 'transparent',
  border: 'currentColor',
  grid: 'currentColor',
  axis: 'currentColor',
  attendee: 'currentColor',
  control: 'currentColor',
  band: 'currentColor',
  bandOpacity: 0.2,
  positive: 'currentColor',
  warning: 'currentColor',
  danger: 'currentColor',
  info: 'currentColor',
  primary: 'currentColor',
  categorical: [],
  sequential: [],
  diverging: [],
  fontFamily: 'inherit',
  fontMono: 'inherit',
};

function readVars(): ChartTheme {
  const styles = getComputedStyle(document.documentElement);
  const read = (name: string, fallback = '#000000') => styles.getPropertyValue(name).trim() || fallback;
  const readNumber = (name: string, fallback: number) => {
    const raw = Number.parseFloat(styles.getPropertyValue(name));
    return Number.isFinite(raw) ? raw : fallback;
  };

  const attr = document.documentElement.getAttribute('data-theme');
  const mode: 'light' | 'dark' =
    attr === 'dark'
      ? 'dark'
      : attr === 'light'
        ? 'light'
        : window.matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light';

  return {
    mode,
    text: read('--text'),
    textMuted: read('--text-muted'),
    textSubtle: read('--text-subtle'),
    surface: read('--surface'),
    surfaceRaised: read('--surface-raised'),
    border: read('--border'),
    grid: read('--chart-grid'),
    axis: read('--chart-axis'),
    attendee: read('--chart-attendee'),
    control: read('--chart-control'),
    band: read('--chart-band'),
    bandOpacity: readNumber('--chart-band-opacity', 0.2),
    positive: read('--positive'),
    warning: read('--warning'),
    danger: read('--danger'),
    info: read('--info'),
    primary: read('--primary'),
    categorical: CATEGORICAL_KEYS.map((k) => read(k)),
    sequential: SEQUENTIAL_KEYS.map((k) => read(k)),
    diverging: DIVERGING_KEYS.map((k) => read(k)),
    fontFamily: read('--font-sans', 'inherit'),
    fontMono: read('--font-mono', 'inherit'),
  };
}

/**
 * Subscribes to theme changes and re-reads the tokens.
 *
 * `resolvedTheme` from next-themes covers the explicit toggle; the media query
 * listener covers the "system" setting changing underneath us (macOS auto
 * dark mode at sunset, which people do notice).
 */
export function useChartTheme(): ChartTheme {
  const { resolvedTheme } = useTheme();
  const [theme, setTheme] = React.useState<ChartTheme>(SSR_THEME);

  React.useEffect(() => {
    const sync = () => setTheme(readVars());
    // Deferred a frame: on the very first paint after a toggle, the new
    // variables may not have been committed to the computed style yet.
    const raf = requestAnimationFrame(sync);

    const media = window.matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', sync);
    return () => {
      cancelAnimationFrame(raf);
      media.removeEventListener('change', sync);
    };
  }, [resolvedTheme]);

  return theme;
}

/* --- ECharts option fragments --------------------------------------------- */

/**
 * Shared axis / grid / tooltip styling. Every chart in the product spreads this
 * so a bar chart and a line chart do not disagree about how a gridline looks.
 */
export function baseChartOption(theme: ChartTheme) {
  return {
    backgroundColor: 'transparent',
    color: theme.categorical,
    textStyle: { fontFamily: theme.fontFamily, fontSize: 12, color: theme.textMuted },
    animationDuration: 260,
    animationEasing: 'cubicOut' as const,
    grid: {
      // Left is generous because currency and Rx axis labels are wide; top is
      // tight because the chart title lives in the surrounding Card, not here.
      left: 8,
      right: 8,
      top: 8,
      bottom: 8,
      containLabel: true,
    },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: theme.surfaceRaised,
      borderColor: theme.border,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: theme.text, fontSize: 12, fontFamily: theme.fontFamily },
      axisPointer: {
        type: 'line' as const,
        lineStyle: { color: theme.axis, width: 1, type: 'dashed' as const },
      },
      extraCssText: 'border-radius:8px;box-shadow:0 12px 32px -8px rgb(0 0 0 / 0.25);',
    },
    legend: {
      type: 'scroll' as const,
      icon: 'roundRect',
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 16,
      textStyle: { color: theme.textMuted, fontSize: 12 },
      inactiveColor: theme.textSubtle,
    },
  };
}

export function categoryAxis(theme: ChartTheme, overrides: Record<string, unknown> = {}) {
  return {
    type: 'category' as const,
    axisLine: { lineStyle: { color: theme.border } },
    axisTick: { show: false },
    axisLabel: { color: theme.textMuted, fontSize: 11, hideOverlap: true },
    splitLine: { show: false },
    ...overrides,
  };
}

export function valueAxis(theme: ChartTheme, overrides: Record<string, unknown> = {}) {
  return {
    type: 'value' as const,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: theme.textMuted, fontSize: 11 },
    // Horizontal rules only. Vertical gridlines add ink without adding meaning
    // on a time series, which is most of what this product plots.
    splitLine: { lineStyle: { color: theme.grid, type: 'solid' as const, width: 1 } },
    ...overrides,
  };
}

/**
 * Colour for a series by its semantic role. `attendee` and `control` are fixed
 * across the entire product — the same two colours mean the same two cohorts on
 * every chart, which is the only way a reader can move between the Portfolio and
 * Event Detail views without re-learning the legend.
 */
export function seriesColor(
  theme: ChartTheme,
  role: 'attendee' | 'control' | 'category',
  index = 0,
): string {
  if (role === 'attendee') return theme.attendee;
  if (role === 'control') return theme.control;
  return theme.categorical[index % Math.max(theme.categorical.length, 1)] ?? theme.primary;
}
