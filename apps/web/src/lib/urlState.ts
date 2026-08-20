'use client';

import { useCallback, useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

/**
 * URL-synced filter state.
 *
 * Filters live in the query string, not in React state. Three reasons, all of
 * which matter for this product specifically:
 *
 *  1. An analyst who found something needs to paste the link to a reviewer and
 *     have them see the *same* slice. plan.md §7.0 makes shareable views a
 *     requirement, not a nicety.
 *  2. Saved views (§7.0) are then just a stored query string.
 *  3. Back/forward behave the way people expect when they drill in and out.
 *
 * Multi-valued filters use repeated keys (`?brand=CDX&brand=NRL`) rather than a
 * comma-joined string, because taxonomy labels legitimately contain commas.
 */

export type FilterValue = string | string[] | null | undefined;
export type FilterPatch = Record<string, FilterValue>;

/** Params the filter bar must never clobber when it rewrites the query. */
const PRESERVED_KEYS = new Set(['returnTo', 'tab']);

export function readParam(params: URLSearchParams, key: string): string | null {
  return params.get(key);
}

export function readParams(params: URLSearchParams, key: string): string[] {
  return params.getAll(key);
}

/**
 * Applies a patch to a `URLSearchParams`, returning a new instance. `null` or
 * `[]` removes the key entirely — an absent key and an empty filter must be the
 * same thing, otherwise `?brand=` ends up meaning "brand named empty string".
 */
export function applyPatch(current: URLSearchParams, patch: FilterPatch): URLSearchParams {
  const next = new URLSearchParams(current.toString());
  for (const [key, value] of Object.entries(patch)) {
    next.delete(key);
    if (value === null || value === undefined || value === '') continue;
    if (Array.isArray(value)) {
      for (const v of value) if (v !== '') next.append(key, v);
    } else {
      next.set(key, value);
    }
  }
  // Any change to filters invalidates the page cursor; keeping it would ask the
  // server to continue a scan through a result set that no longer exists.
  next.delete('cursor');
  return next;
}

export function clearFilters(current: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams();
  for (const key of PRESERVED_KEYS) {
    const value = current.get(key);
    if (value) next.set(key, value);
  }
  return next;
}

export function toQueryString(params: URLSearchParams): string {
  const s = params.toString();
  return s ? `?${s}` : '';
}

export interface UrlFilterState {
  params: URLSearchParams;
  /** Single-valued read. */
  get: (key: string) => string | null;
  /** Multi-valued read. */
  getAll: (key: string) => string[];
  /** Merge a patch into the URL. */
  set: (patch: FilterPatch, options?: { replace?: boolean }) => void;
  /** Drop everything except preserved keys. */
  reset: () => void;
  /** Replace the whole query (used when applying a saved view). */
  replaceAll: (query: string) => void;
  /** True when anything beyond the preserved keys is set. */
  hasActiveFilters: boolean;
}

export function useUrlFilters(): UrlFilterState {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // `useSearchParams()` returns a ReadonlyURLSearchParams; copy so callers can
  // iterate and mutate without fighting the type.
  const params = useMemo(() => new URLSearchParams(searchParams.toString()), [searchParams]);

  const push = useCallback(
    (next: URLSearchParams, replace: boolean) => {
      const href = `${pathname}${toQueryString(next)}`;
      // `scroll: false` — re-filtering a table should not throw the user back to
      // the top of the page.
      if (replace) router.replace(href, { scroll: false });
      else router.push(href, { scroll: false });
    },
    [pathname, router],
  );

  const set = useCallback(
    (patch: FilterPatch, options?: { replace?: boolean }) => {
      push(applyPatch(params, patch), options?.replace ?? false);
    },
    [params, push],
  );

  const reset = useCallback(() => {
    push(clearFilters(params), false);
  }, [params, push]);

  const replaceAll = useCallback(
    (query: string) => {
      push(new URLSearchParams(query.startsWith('?') ? query.slice(1) : query), false);
    },
    [push],
  );

  const hasActiveFilters = useMemo(
    () => [...params.keys()].some((k) => !PRESERVED_KEYS.has(k)),
    [params],
  );

  return {
    params,
    get: (key) => params.get(key),
    getAll: (key) => params.getAll(key),
    set,
    reset,
    replaceAll,
    hasActiveFilters,
  };
}
