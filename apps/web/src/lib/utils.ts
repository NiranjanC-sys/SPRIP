import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Class composer used by every component. `twMerge` is what makes the `className`
 * prop on our primitives actually work — without it a caller's `px-6` loses to
 * the variant's `px-4` on specificity ties and the override silently does
 * nothing.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Stable id generator for aria wiring in components that render before hydration. */
let idCounter = 0;
export function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

/**
 * Only same-origin, non-protocol-relative paths are safe to send a user to after
 * login. `//evil.com` and `https://evil.com` both have to be refused, and
 * `/\evil.com` is treated as protocol-relative by some browsers — hence the
 * backslash check.
 */
export function isSafeReturnPath(value: string | null | undefined): value is string {
  if (!value) return false;
  if (!value.startsWith('/')) return false;
  if (value.startsWith('//') || value.startsWith('/\\')) return false;
  if (value.includes('://')) return false;
  return true;
}

export function safeReturnPath(value: string | null | undefined, fallback: string): string {
  return isSafeReturnPath(value) ? value : fallback;
}

/** Trailing-edge debounce for search inputs and resize handlers. */
export function debounce<TArgs extends unknown[]>(
  fn: (...args: TArgs) => void,
  waitMs: number,
): ((...args: TArgs) => void) & { cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const wrapped = (...args: TArgs) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), waitMs);
  };
  wrapped.cancel = () => {
    if (timer) clearTimeout(timer);
  };
  return wrapped;
}

/** `['a','b','c'] -> "a, b and c"`. Used in filter chip summaries and exports. */
export function joinReadable(parts: readonly string[]): string {
  if (parts.length === 0) return '';
  if (parts.length === 1) return parts[0] ?? '';
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}

/** UPPER_SNAKE -> Title Case. Enum values are shown to users verbatim otherwise. */
export function humanizeEnum(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .map((w) => (w.length > 0 ? w[0]!.toUpperCase() + w.slice(1) : w))
    .join(' ');
}
