/**
 * Public surface of the query layer.
 *
 * Dashboards import from here, never from `../client` directly — that keeps the
 * fetch wrapper's contract (schemas, idempotency, error mapping) enforceable in
 * one place instead of relying on every call site to remember it.
 */
export * from './session';
export * from './shell';
export * from './uploads';
export { qk, queryKeys, analyticalRoots, type FilterKey } from '../queryKeys';
export { STALE } from '../queryClient';
export { api, apiRequest, buildQueryString } from '../client';
export * from '../errors';
