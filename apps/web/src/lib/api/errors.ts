/**
 * The stable error envelope (plan.md §13) and its typed shells.
 *
 * The API always answers a failure with:
 *   { error: { code, message, details?, requestId? } }
 *
 * Callers branch on the *class*, never on the status number, so a future
 * status-code change does not ripple into every component. `requestId` is
 * surfaced in the UI because it is the only thing a user can quote to support.
 */

export interface ApiErrorEnvelope {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  requestId?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: Record<string, unknown>;
  readonly requestId?: string;

  constructor(status: number, envelope: ApiErrorEnvelope) {
    super(envelope.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = envelope.code;
    this.details = envelope.details;
    this.requestId = envelope.requestId;
  }
}

/** 401. The client kicks the session-expired flow; components rarely see this. */
export class UnauthorizedError extends ApiError {
  constructor(envelope: ApiErrorEnvelope) {
    super(401, envelope);
    this.name = 'UnauthorizedError';
  }
}

/**
 * 403. Deliberately carries no resource identity: plan.md §5.3 requires a safe
 * 403, and echoing "you cannot see event 91f2…" confirms the row exists.
 */
export class ForbiddenError extends ApiError {
  constructor(envelope: ApiErrorEnvelope) {
    super(403, envelope);
    this.name = 'ForbiddenError';
  }
}

export class NotFoundError extends ApiError {
  constructor(envelope: ApiErrorEnvelope) {
    super(404, envelope);
    this.name = 'NotFoundError';
  }
}

/** 409. Illegal workflow transition, stale write, or a replayed idempotency key. */
export class ConflictError extends ApiError {
  constructor(envelope: ApiErrorEnvelope) {
    super(409, envelope);
    this.name = 'ConflictError';
  }
}

/** 422 with field-level `details`, so FormField can bind them to inputs. */
export class ValidationError extends ApiError {
  constructor(envelope: ApiErrorEnvelope) {
    super(422, envelope);
    this.name = 'ValidationError';
  }

  /** `{ email: ["already in use"] }` — shape the API commits to for 422. */
  get fieldErrors(): Record<string, string[]> {
    const raw = this.details?.['fields'];
    if (!raw || typeof raw !== 'object') return {};
    const out: Record<string, string[]> = {};
    for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
      if (Array.isArray(value)) out[key] = value.map(String);
      else if (typeof value === 'string') out[key] = [value];
    }
    return out;
  }
}

export class RateLimitedError extends ApiError {
  readonly retryAfterSeconds?: number;
  constructor(envelope: ApiErrorEnvelope, retryAfterSeconds?: number) {
    super(429, envelope);
    this.name = 'RateLimitedError';
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** Transport failure, DNS, offline, abort. Distinct from any HTTP status. */
export class NetworkError extends Error {
  override readonly cause?: unknown;
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'NetworkError';
    this.cause = cause;
  }
}

/**
 * The response parsed but did not match its zod schema. This is a *server*
 * contract breach and must be loud in development rather than crashing a
 * component three renders later on `undefined.map`.
 */
export class ResponseShapeError extends Error {
  readonly path: string;
  readonly issues: string[];
  constructor(path: string, issues: string[]) {
    super(`Response from ${path} did not match its schema: ${issues.join('; ')}`);
    this.name = 'ResponseShapeError';
    this.path = path;
    this.issues = issues;
  }
}

export function isForbidden(error: unknown): error is ForbiddenError {
  return error instanceof ForbiddenError;
}

export function isUnauthorized(error: unknown): error is UnauthorizedError {
  return error instanceof UnauthorizedError;
}

export function isConflict(error: unknown): error is ConflictError {
  return error instanceof ConflictError;
}

/** Message safe to render. Never leaks a stack or an internal identifier. */
export function toDisplayMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof NetworkError) {
    return 'Could not reach the service. Check your connection and try again.';
  }
  if (error instanceof ResponseShapeError) {
    return 'The service returned an unexpected response. This has been logged.';
  }
  if (error instanceof Error && error.message) return error.message;
  return 'Something went wrong.';
}

export function toRequestId(error: unknown): string | undefined {
  return error instanceof ApiError ? error.requestId : undefined;
}
