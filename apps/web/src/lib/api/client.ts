import { z } from 'zod';

import { env } from '@/lib/env';

import {
  ApiError,
  ConflictError,
  ForbiddenError,
  NetworkError,
  NotFoundError,
  RateLimitedError,
  ResponseShapeError,
  UnauthorizedError,
  ValidationError,
  type ApiErrorEnvelope,
} from './errors';

/**
 * The single fetch wrapper. Nothing in the app calls `fetch` directly.
 *
 * Responsibilities, in the order they bite:
 *  - session cookie transport (`credentials: 'include'`) and CSRF header;
 *  - a correlation id on every request so a UI report maps to a server log;
 *  - envelope parsing into typed errors;
 *  - 401 -> one-shot redirect to the session-expired screen;
 *  - retry with backoff for idempotent GETs only;
 *  - `Idempotency-Key` for mutations (plan.md §13);
 *  - optional zod validation of the payload.
 */

const CSRF_COOKIE = 'sr_csrf';
const CSRF_HEADER = 'x-csrf-token';
const REQUEST_ID_HEADER = 'x-request-id';
const IDEMPOTENCY_HEADER = 'Idempotency-Key';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface RequestOptions<TOut> {
  method?: HttpMethod;
  /** Serialised to JSON unless it is a FormData/Blob, which is passed through. */
  body?: unknown;
  query?: QueryParams;
  /**
   * Validated with this schema when provided. Strongly recommended.
   *
   * The third generic is `unknown` on purpose: schemas that use `.default()` or
   * `.catch()` have an input type that differs from their output type, and
   * pinning input to `TOut` would reject exactly the schemas that are most
   * defensive about a sloppy payload.
   */
  schema?: z.ZodType<TOut, z.ZodTypeDef, unknown>;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  /** Mutations only. Generated automatically when `true`. */
  idempotencyKey?: string | true;
  /** Server components must forward the incoming Cookie header explicitly. */
  cookie?: string;
  /** Opt out of the 401 redirect — the login form needs the raw error. */
  suppressAuthRedirect?: boolean;
  /** GET only. Default 2 retries; set 0 for a request that must not repeat. */
  retries?: number;
}

export type QueryParams = Record<
  string,
  string | number | boolean | null | undefined | readonly (string | number)[]
>;

/* --- helpers ------------------------------------------------------------- */

export function buildQueryString(params: QueryParams | undefined): string {
  if (!params) return '';
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue;
    if (Array.isArray(value)) {
      // Repeated keys rather than a comma list: taxonomy values legitimately
      // contain commas ("EMEA West, North").
      for (const item of value) search.append(key, String(item));
    } else {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

function readCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : undefined;
}

function newRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  // Non-secure fallback for older runtimes; this value is a log correlator, not
  // a security token, so Math.random is acceptable here.
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

const envelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.record(z.unknown()).optional(),
    requestId: z.string().optional(),
  }),
});

function toApiError(status: number, envelope: ApiErrorEnvelope, retryAfter?: number): ApiError {
  switch (status) {
    case 401:
      return new UnauthorizedError(envelope);
    case 403:
      return new ForbiddenError(envelope);
    case 404:
      return new NotFoundError(envelope);
    case 409:
      return new ConflictError(envelope);
    case 422:
      return new ValidationError(envelope);
    case 429:
      return new RateLimitedError(envelope, retryAfter);
    default:
      return new ApiError(status, envelope);
  }
}

/**
 * Sends the browser to the session-expired screen exactly once. Without the
 * latch, a dashboard firing eight parallel queries produces eight redirects and
 * the user's `returnTo` becomes whichever one lost the race.
 */
let sessionExpiredHandled = false;
function handleSessionExpired(): void {
  if (typeof window === 'undefined' || sessionExpiredHandled) return;
  sessionExpiredHandled = true;
  const returnTo = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/session-expired?returnTo=${encodeURIComponent(returnTo)}`);
}

/** Called after a successful login so a later 401 can redirect again. */
export function resetSessionExpiredLatch(): void {
  sessionExpiredHandled = false;
}

const RETRYABLE_STATUSES = new Set([408, 425, 429, 500, 502, 503, 504]);
const BASE_BACKOFF_MS = 300;

function backoffDelay(attempt: number): number {
  // Exponential with jitter; jitter matters because a dashboard mounts ~8
  // queries at once and they would otherwise retry in lockstep.
  const ceiling = BASE_BACKOFF_MS * 2 ** attempt;
  return ceiling / 2 + Math.random() * (ceiling / 2);
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(new DOMException('Aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

/* --- the request --------------------------------------------------------- */

export async function apiRequest<TOut = unknown>(
  path: string,
  options: RequestOptions<TOut> = {},
): Promise<TOut> {
  const method = options.method ?? 'GET';
  const isIdempotent = method === 'GET';
  const maxRetries = isIdempotent ? (options.retries ?? 2) : 0;

  const url = `${env.apiBaseUrl}${path}${buildQueryString(options.query)}`;

  const headers: Record<string, string> = {
    accept: 'application/json',
    [REQUEST_ID_HEADER]: newRequestId(),
    ...options.headers,
  };

  // CSRF applies to state-changing verbs only. The token is a readable cookie
  // paired with the httpOnly session cookie — the standard double-submit
  // pattern, which is why reading it from document.cookie is correct here.
  if (!isIdempotent) {
    const token = readCookie(CSRF_COOKIE);
    if (token) headers[CSRF_HEADER] = token;
    if (options.idempotencyKey) {
      headers[IDEMPOTENCY_HEADER] =
        options.idempotencyKey === true ? newRequestId() : options.idempotencyKey;
    }
  }

  // Server components have no ambient cookie jar; the caller forwards it.
  if (options.cookie) headers['cookie'] = options.cookie;

  let payload: BodyInit | undefined;
  if (options.body !== undefined) {
    if (options.body instanceof FormData || options.body instanceof Blob) {
      payload = options.body;
    } else {
      headers['content-type'] = 'application/json';
      payload = JSON.stringify(options.body);
    }
  }

  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: payload,
        credentials: 'include',
        // Analytical payloads are cached by TanStack Query with explicit
        // staleTimes; letting the HTTP cache also hold them produces two
        // caches with different invalidation rules and a stale KPI card.
        cache: 'no-store',
        ...(options.signal ? { signal: options.signal } : {}),
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
      lastError = new NetworkError('Request failed before a response was received.', cause);
      if (attempt < maxRetries) {
        await sleep(backoffDelay(attempt), options.signal);
        continue;
      }
      throw lastError;
    }

    if (response.ok) {
      if (response.status === 204) return undefined as TOut;
      const text = await response.text();
      if (!text) return undefined as TOut;

      let json: unknown;
      try {
        json = JSON.parse(text) as unknown;
      } catch {
        throw new ResponseShapeError(path, ['response body was not valid JSON']);
      }

      if (!options.schema) return json as TOut;
      const parsed = options.schema.safeParse(json);
      if (!parsed.success) {
        throw new ResponseShapeError(
          path,
          parsed.error.issues.map((i) => `${i.path.join('.') || '<root>'}: ${i.message}`),
        );
      }
      return parsed.data;
    }

    // --- failure path ---
    const retryAfterRaw = response.headers.get('retry-after');
    const retryAfter = retryAfterRaw ? Number(retryAfterRaw) : undefined;
    const envelope = await readEnvelope(response);
    const error = toApiError(response.status, envelope, retryAfter);

    if (response.status === 401 && !options.suppressAuthRedirect) {
      handleSessionExpired();
      throw error;
    }

    if (isIdempotent && attempt < maxRetries && RETRYABLE_STATUSES.has(response.status)) {
      lastError = error;
      const waitMs =
        retryAfter && Number.isFinite(retryAfter) ? retryAfter * 1000 : backoffDelay(attempt);
      await sleep(waitMs, options.signal);
      continue;
    }

    throw error;
  }

  throw lastError ?? new NetworkError('Request failed.');
}

async function readEnvelope(response: Response): Promise<ApiErrorEnvelope> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  const parsed = envelopeSchema.safeParse(body);
  if (parsed.success) {
    return {
      ...parsed.data.error,
      // Prefer the header: a proxy that swallowed the body still sets it.
      requestId: response.headers.get(REQUEST_ID_HEADER) ?? parsed.data.error.requestId,
    };
  }
  // A gateway 502 has no envelope. Synthesise one so callers see one shape.
  return {
    code: `HTTP_${response.status}`,
    message: response.statusText || 'The request could not be completed.',
    ...(response.headers.get(REQUEST_ID_HEADER)
      ? { requestId: response.headers.get(REQUEST_ID_HEADER) as string }
      : {}),
  };
}

/* --- verb sugar ---------------------------------------------------------- */

export const api = {
  get<T>(path: string, options: Omit<RequestOptions<T>, 'method' | 'body'> = {}) {
    return apiRequest<T>(path, { ...options, method: 'GET' });
  },
  post<T>(path: string, body?: unknown, options: Omit<RequestOptions<T>, 'method' | 'body'> = {}) {
    return apiRequest<T>(path, { idempotencyKey: true, ...options, method: 'POST', body });
  },
  put<T>(path: string, body?: unknown, options: Omit<RequestOptions<T>, 'method' | 'body'> = {}) {
    return apiRequest<T>(path, { idempotencyKey: true, ...options, method: 'PUT', body });
  },
  patch<T>(path: string, body?: unknown, options: Omit<RequestOptions<T>, 'method' | 'body'> = {}) {
    return apiRequest<T>(path, { idempotencyKey: true, ...options, method: 'PATCH', body });
  },
  delete<T>(path: string, options: Omit<RequestOptions<T>, 'method' | 'body'> = {}) {
    return apiRequest<T>(path, { idempotencyKey: true, ...options, method: 'DELETE' });
  },
} as const;
