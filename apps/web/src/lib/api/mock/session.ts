import { Role, type Role as RoleType } from '../enums';

/**
 * Dev-only session transport for `NEXT_PUBLIC_API_MOCK=1`.
 *
 * ---------------------------------------------------------------------------
 * THIS IS NOT AN AUTHENTICATION MECHANISM.
 * ---------------------------------------------------------------------------
 * The real product keeps the session in an httpOnly, Secure, SameSite=Lax
 * cookie the browser cannot read, and roles are resolved server-side from the
 * application database on every request (docs/PLAN_REVIEW.md F-3). None of that
 * exists yet because the API is being built in parallel, so mock mode stores a
 * readable, unsigned cookie purely so `middleware.ts` and the server layouts can
 * exercise their real gating logic against a real cookie.
 *
 * Every read path is gated on `env.apiMock`, so with the flag off this module is
 * unreachable and the bundler drops it. If you ever find this code running with
 * the flag off, that is the bug — not the cookie format.
 */

export const DEV_SESSION_COOKIE = 'sr_dev_session';
/** The real deployment's opaque session cookie. Middleware checks for this one first. */
export const SESSION_COOKIE = 'sr_session';

export interface DevSession {
  userId: string;
  email: string;
  displayName: string;
  roles: RoleType[];
  tenantId: string;
  tenantName: string;
  tenantCode: string;
  syntheticMode: boolean;
}

/** Role selected by the email local part, so a reviewer can demo every gate. */
const ROLE_BY_LOCAL_PART: Readonly<Record<string, RoleType>> = {
  platform: Role.PLATFORM_ADMIN,
  admin: Role.PHARMA_ADMIN,
  vendor: Role.VENDOR_CONTRIBUTOR,
  steward: Role.DATA_STEWARD,
  analytics: Role.ANALYTICS_LEAD,
  finance: Role.FINANCE_REVIEWER,
  compliance: Role.COMPLIANCE_REVIEWER,
  brand: Role.BRAND_MANAGER,
  exec: Role.EXECUTIVE_VIEWER,
};

export const DEMO_LOGINS: ReadonlyArray<{ email: string; label: string; role: RoleType }> =
  Object.entries(ROLE_BY_LOCAL_PART).map(([local, role]) => ({
    email: `${local}@northwind.demo`,
    label: role,
    role,
  }));

export function rolesForEmail(email: string): RoleType[] {
  const local = email.split('@')[0]?.toLowerCase().trim() ?? '';
  const matched = ROLE_BY_LOCAL_PART[local];
  // Unknown local part gets the least-privileged real role rather than an empty
  // list, so an arbitrary demo email still lands somewhere coherent.
  return [matched ?? Role.EXECUTIVE_VIEWER];
}

/* --- encoding ------------------------------------------------------------ */

// base64url so the value is cookie-safe without percent-encoding noise.
function toBase64Url(input: string): string {
  const bytes = new TextEncoder().encode(input);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  const base64 = typeof btoa === 'function' ? btoa(binary) : Buffer.from(input, 'utf8').toString('base64');
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(input: string): string {
  const base64 = input.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
  if (typeof atob === 'function') {
    const binary = atob(padded);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  }
  return Buffer.from(padded, 'base64').toString('utf8');
}

export function encodeDevSession(session: DevSession): string {
  return toBase64Url(JSON.stringify(session));
}

export function decodeDevSession(raw: string | undefined): DevSession | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(fromBase64Url(raw));
    if (!parsed || typeof parsed !== 'object') return null;
    const candidate = parsed as Partial<DevSession>;
    if (!candidate.userId || !Array.isArray(candidate.roles)) return null;
    return candidate as DevSession;
  } catch {
    // A malformed cookie is treated as no session — fail closed.
    return null;
  }
}
