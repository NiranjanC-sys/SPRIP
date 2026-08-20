import { QueryClient, type DefaultOptions } from '@tanstack/react-query';

import { ApiError, ForbiddenError, NotFoundError, UnauthorizedError, ValidationError } from './errors';

/**
 * Cache policy.
 *
 * Analytical results here are immutable per (data version × run × finance
 * version) — a published number does not change under you. That makes a
 * generous `staleTime` correct rather than risky: the invalidation trigger is a
 * *publish event*, not the clock. The named tiers below are what dashboards
 * should pick from; ad-hoc millisecond literals in a hook are a smell.
 */
export const STALE = {
  /** Session, tenant context. Re-checked on focus so a revoked role bites fast. */
  session: 60_000,
  /** Reference data for filters: brands, taxonomies. Changes by admin action. */
  reference: 10 * 60_000,
  /** Published analytical payloads, keyed by data version. */
  analytical: 5 * 60_000,
  /** Freshness, run status, upload progress. Deliberately short. */
  operational: 15_000,
  /** Never cache: exports, one-shot lookups. */
  none: 0,
} as const;

/**
 * A 4xx that describes the *request* will not become correct by repeating it.
 * Retrying a 403 also generates a second PERMISSION_DENIED audit row for the
 * same user action, which pollutes the compliance record.
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (
    error instanceof UnauthorizedError ||
    error instanceof ForbiddenError ||
    error instanceof NotFoundError ||
    error instanceof ValidationError
  ) {
    return false;
  }
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  // The client already retried the transport twice; one more round-trip here
  // covers a server that was mid-restart.
  return failureCount < 1;
}

const defaultOptions: DefaultOptions = {
  queries: {
    staleTime: STALE.analytical,
    gcTime: 15 * 60_000,
    retry: shouldRetry,
    refetchOnWindowFocus: false,
    // A reviewer who regains connectivity should see live data, but a focus
    // refetch on every alt-tab makes a dense dashboard flicker for no gain.
    refetchOnReconnect: true,
    throwOnError: false,
  },
  mutations: {
    // Mutations carry an Idempotency-Key, but a blind retry still risks a
    // duplicate audit row if the key was not echoed. Callers opt in explicitly.
    retry: false,
  },
};

export function createQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions });
}
