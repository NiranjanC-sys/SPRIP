/**
 * Display formatting for every number the product shows.
 *
 * Two rules the whole team depends on:
 *
 *   1. A value the API could not estimate renders as `EM_DASH`, never as `0`.
 *      plan.md §12.3 is explicit that a failed evidence gate produces a reason,
 *      not a zero lift — so `null` must be visually distinct from zero
 *      everywhere, including inside chart tooltips and CSV exports.
 *   2. Intervals print as `point [lo, hi]`. A point estimate without its
 *      interval is not an acceptable rendering of a causal result.
 *
 * Locale/currency come from the tenant, never from the browser: two reviewers
 * looking at the same evidence page must read the same digits (F-14 — no
 * implicit conversion).
 */

export const EM_DASH = '—';

export interface FormatOptions {
  locale?: string;
  /** ISO-4217, from `tenant.reportingCurrency`. */
  currency?: string;
}

const DEFAULT_LOCALE = 'en-US';

// Intl.NumberFormat construction is not free and these run inside table cell
// renderers, so the formatters are memoised by their option signature.
const cache = new Map<string, Intl.NumberFormat>();
function nf(locale: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let found = cache.get(key);
  if (!found) {
    found = new Intl.NumberFormat(locale, options);
    cache.set(key, found);
  }
  return found;
}

function isMissing(value: number | null | undefined): value is null | undefined {
  return value === null || value === undefined || Number.isNaN(value);
}

/** Whole counts: attendees, events, rows. */
export function formatInteger(value: number | null | undefined, o: FormatOptions = {}): string {
  if (isMissing(value)) return EM_DASH;
  return nf(o.locale ?? DEFAULT_LOCALE, { maximumFractionDigits: 0 }).format(value);
}

/** Estimates and ratios. Defaults to one decimal — lift is not a whole number. */
export function formatDecimal(
  value: number | null | undefined,
  digits = 1,
  o: FormatOptions = {},
): string {
  if (isMissing(value)) return EM_DASH;
  return nf(o.locale ?? DEFAULT_LOCALE, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** Money. `currency` is required for correctness; falling back to USD silently
 *  would misreport a EUR tenant, so an absent currency renders unitless. */
export function formatCurrency(
  value: number | null | undefined,
  o: FormatOptions = {},
): string {
  if (isMissing(value)) return EM_DASH;
  if (!o.currency) return formatDecimal(value, 0, o);
  return nf(o.locale ?? DEFAULT_LOCALE, {
    style: 'currency',
    currency: o.currency,
    maximumFractionDigits: 0,
  }).format(value);
}

/** Compact money for KPI headlines, e.g. `$1.2M`. Full value goes in the tooltip. */
export function formatCurrencyCompact(
  value: number | null | undefined,
  o: FormatOptions = {},
): string {
  if (isMissing(value)) return EM_DASH;
  if (!o.currency) return formatCompact(value, o);
  return nf(o.locale ?? DEFAULT_LOCALE, {
    style: 'currency',
    currency: o.currency,
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatCompact(value: number | null | undefined, o: FormatOptions = {}): string {
  if (isMissing(value)) return EM_DASH;
  return nf(o.locale ?? DEFAULT_LOCALE, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

/** `value` is a ratio (0.42 -> "42.0%"), matching how the API returns rates. */
export function formatPercent(
  value: number | null | undefined,
  digits = 1,
  o: FormatOptions = {},
): string {
  if (isMissing(value)) return EM_DASH;
  return nf(o.locale ?? DEFAULT_LOCALE, {
    style: 'percent',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** Signed delta for comparison-period rows: `+3.2%` / `-1.0%`. */
export function formatSignedPercent(
  value: number | null | undefined,
  digits = 1,
  o: FormatOptions = {},
): string {
  if (isMissing(value)) return EM_DASH;
  return nf(o.locale ?? DEFAULT_LOCALE, {
    style: 'percent',
    signDisplay: 'exceptZero',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function formatMultiple(value: number | null | undefined, o: FormatOptions = {}): string {
  if (isMissing(value)) return EM_DASH;
  return `${formatDecimal(value, 2, o)}×`;
}

export interface Interval {
  point: number | null;
  lower: number | null;
  upper: number | null;
}

type ValueFormatter = (v: number | null | undefined, o?: FormatOptions) => string;

/**
 * `point [lower, upper]`. If the point exists but the bounds do not, the point
 * is shown alone — that is a legitimate state for a descriptive metric. If the
 * point is null the whole thing is a dash: there is no estimate to qualify.
 */
export function formatInterval(
  interval: Interval | null | undefined,
  format: ValueFormatter = formatDecimal as ValueFormatter,
  o: FormatOptions = {},
): string {
  if (!interval || isMissing(interval.point)) return EM_DASH;
  const point = format(interval.point, o);
  if (isMissing(interval.lower) || isMissing(interval.upper)) return point;
  return `${point} [${format(interval.lower, o)}, ${format(interval.upper, o)}]`;
}

/** Bounds only, for a column that renders the point estimate separately. */
export function formatRange(
  lower: number | null | undefined,
  upper: number | null | undefined,
  format: ValueFormatter = formatDecimal as ValueFormatter,
  o: FormatOptions = {},
): string {
  if (isMissing(lower) || isMissing(upper)) return EM_DASH;
  return `${format(lower, o)} – ${format(upper, o)}`;
}

/* --- dates --------------------------------------------------------------- */

function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** `2026-03` or `2026-03-01` -> `Mar 2026`. The x-axis label of every panel. */
export function formatMonth(value: string | Date | null | undefined, o: FormatOptions = {}): string {
  // The API sends panel periods as `YYYY-MM`; Date() parses that as a month
  // boundary in some engines and as invalid in others, so normalise first.
  const normalised =
    typeof value === 'string' && /^\d{4}-\d{2}$/.test(value) ? `${value}-01` : value;
  const d = toDate(normalised);
  if (!d) return EM_DASH;
  return new Intl.DateTimeFormat(o.locale ?? DEFAULT_LOCALE, {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(d);
}

export function formatDate(value: string | Date | null | undefined, o: FormatOptions = {}): string {
  const d = toDate(value);
  if (!d) return EM_DASH;
  return new Intl.DateTimeFormat(o.locale ?? DEFAULT_LOCALE, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(d);
}

/** Timestamps are UTC everywhere: an audit trail read across regions must not
 *  shift. The zone is printed so nobody has to guess. */
export function formatDateTime(
  value: string | Date | null | undefined,
  o: FormatOptions = {},
): string {
  const d = toDate(value);
  if (!d) return EM_DASH;
  const formatted = new Intl.DateTimeFormat(o.locale ?? DEFAULT_LOCALE, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: 'UTC',
  }).format(d);
  return `${formatted} UTC`;
}

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

/** Freshness indicator: "4h ago". Coarse on purpose — a data feed measured to
 *  the second invites false confidence about delivery latency. */
export function formatRelativeTime(
  value: string | Date | null | undefined,
  now: Date = new Date(),
  o: FormatOptions = {},
): string {
  const d = toDate(value);
  if (!d) return EM_DASH;
  const seconds = Math.round((d.getTime() - now.getTime()) / 1000);
  const abs = Math.abs(seconds);
  const rtf = new Intl.RelativeTimeFormat(o.locale ?? DEFAULT_LOCALE, { numeric: 'auto' });
  if (abs < MINUTE) return rtf.format(seconds, 'second');
  if (abs < HOUR) return rtf.format(Math.round(seconds / MINUTE), 'minute');
  if (abs < DAY) return rtf.format(Math.round(seconds / HOUR), 'hour');
  return rtf.format(Math.round(seconds / DAY), 'day');
}

/** Job/run durations on the Data & Model Health dashboard. */
export function formatDuration(seconds: number | null | undefined): string {
  if (isMissing(seconds)) return EM_DASH;
  if (seconds < MINUTE) return `${Math.round(seconds)}s`;
  if (seconds < HOUR) {
    const m = Math.floor(seconds / MINUTE);
    return `${m}m ${Math.round(seconds - m * MINUTE)}s`;
  }
  const h = Math.floor(seconds / HOUR);
  return `${h}h ${Math.round((seconds - h * HOUR) / MINUTE)}m`;
}

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const;
const BYTE_STEP = 1024;

export function formatBytes(bytes: number | null | undefined): string {
  if (isMissing(bytes)) return EM_DASH;
  let value = bytes;
  let unit = 0;
  while (value >= BYTE_STEP && unit < BYTE_UNITS.length - 1) {
    value /= BYTE_STEP;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${BYTE_UNITS[unit]}`;
}

/** Bundled export so charts and tables can be handed one object. */
export const formatters = {
  integer: formatInteger,
  decimal: formatDecimal,
  currency: formatCurrency,
  currencyCompact: formatCurrencyCompact,
  compact: formatCompact,
  percent: formatPercent,
  signedPercent: formatSignedPercent,
  multiple: formatMultiple,
  interval: formatInterval,
  range: formatRange,
  month: formatMonth,
  date: formatDate,
  dateTime: formatDateTime,
  relativeTime: formatRelativeTime,
  duration: formatDuration,
  bytes: formatBytes,
} as const;

export type Formatters = typeof formatters;
/** Names a dashboard can pass as a prop instead of a function reference. */
export type FormatterName = keyof Formatters;
