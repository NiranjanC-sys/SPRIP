'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';
import { useChartTheme } from './chartTheme';

export interface SparklineProps {
  /** Ordered values; `null` is a gap and breaks the line. */
  values: ReadonlyArray<number | null>;
  /** Drives the line colour: up-is-good vs. up-is-bad differs per metric. */
  higherIsBetter?: boolean;
  className?: string;
  width?: number;
  height?: number;
  /** Screen-reader description. The KPI value itself is the accessible content. */
  label?: string;
}

/**
 * Trend line for a KPI card.
 *
 * Hand-drawn SVG rather than a second ECharts instance: a KPI row mounts five of
 * these, and five canvases with their own resize observers cost far more than
 * five paths. It is decorative — the number and its comparison are the content.
 */
export function Sparkline({
  values,
  higherIsBetter = true,
  className,
  width = 96,
  height = 28,
  label,
}: SparklineProps) {
  const theme = useChartTheme();

  const path = React.useMemo(() => {
    const points = values.map((v, i) => ({ v, i }));
    const known = points.filter((p): p is { v: number; i: number } => typeof p.v === 'number');
    if (known.length < 2) return null;

    const xs = values.length - 1;
    const min = Math.min(...known.map((p) => p.v));
    const max = Math.max(...known.map((p) => p.v));
    const span = max - min || 1;
    const pad = 2;

    const x = (i: number) => (xs === 0 ? width / 2 : (i / xs) * (width - pad * 2) + pad);
    const y = (v: number) => height - pad - ((v - min) / span) * (height - pad * 2);

    // Segments split on nulls so a gap is a gap, not an interpolated line.
    const segments: string[] = [];
    let current: string[] = [];
    for (const p of points) {
      if (typeof p.v !== 'number') {
        if (current.length > 1) segments.push(current.join(' '));
        current = [];
        continue;
      }
      current.push(`${current.length === 0 ? 'M' : 'L'}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`);
    }
    if (current.length > 1) segments.push(current.join(' '));

    const first = known[0]?.v ?? 0;
    const last = known[known.length - 1]?.v ?? 0;
    const rising = last >= first;
    const good = higherIsBetter ? rising : !rising;

    return { d: segments.join(' '), stroke: good ? theme.positive : theme.danger };
  }, [values, higherIsBetter, width, height, theme]);

  if (!path) {
    return <div className={cn('h-7', className)} aria-hidden="true" />;
  }

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={cn('overflow-visible', className)}
      role={label ? 'img' : 'presentation'}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      <path d={path.d} fill="none" stroke={path.stroke} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
