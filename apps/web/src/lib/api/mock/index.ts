import { env } from '@/lib/env';

import * as fx from './fixtures';
import {
  DEV_SESSION_COOKIE,
  decodeDevSession,
  encodeDevSession,
  rolesForEmail,
  type DevSession,
} from './session';

/**
 * Lightweight fetch interceptor for `NEXT_PUBLIC_API_MOCK=1`.
 *
 * MSW is deliberately not used: it needs a service worker registered from
 * `public/`, which fights Next's dev overlay and does not run at all during
 * `next build`'s prerender pass. A `globalThis.fetch` patch is ~80 lines, works
 * identically in the browser and in the Node prerender, and disappears entirely
 * when the flag is off.
 *
 * Only `env.apiBaseUrl`-prefixed URLs are intercepted; everything else falls
 * through untouched, so Next's own RSC and HMR traffic is unaffected.
 */

type Handler = (request: MockRequest) => Promise<Response> | Response;

interface MockRequest {
  method: string;
  /** Path *after* the API base, e.g. `/auth/me`. */
  path: string;
  search: URLSearchParams;
  body: unknown;
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json', 'x-request-id': `mock-${Date.now().toString(36)}` },
  });
}

function errorEnvelope(status: number, code: string, message: string): Response {
  return json({ error: { code, message, requestId: `mock-${Date.now().toString(36)}` } }, status);
}

function writeDevSessionCookie(session: DevSession): void {
  if (typeof document === 'undefined') return;
  // Not httpOnly and not signed — see the warning in ./session.ts. Session-
  // scoped (no Max-Age) so closing the browser ends the demo session.
  document.cookie = `${DEV_SESSION_COOKIE}=${encodeDevSession(session)}; Path=/; SameSite=Lax`;
}

function clearDevSessionCookie(): void {
  if (typeof document === 'undefined') return;
  document.cookie = `${DEV_SESSION_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}

function readDevSessionCookie(): DevSession | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${DEV_SESSION_COOKIE}=([^;]*)`));
  if (!match?.[1]) return null;
  return decodeDevSession(match[1]);
}

/** Path pattern -> handler. First match wins, so put specific paths first. */
const routes: ReadonlyArray<[RegExp, string, Handler]> = [
  [
    /^\/auth\/login$/,
    'POST',
    (req) => {
      const body = (req.body ?? {}) as { email?: string; password?: string; totpCode?: string };
      const email = (body.email ?? '').trim();
      if (!email || !body.password) {
        return errorEnvelope(422, 'INVALID_CREDENTIALS', 'Enter your email and password.');
      }
      // A deliberately explicit demo rule, so the "account locked" and "invalid
      // credentials" branches of the login form are both reachable by hand.
      if (email.startsWith('locked@')) {
        return errorEnvelope(423, 'ACCOUNT_LOCKED', 'This account is locked. Contact your administrator.');
      }
      if (email.startsWith('disabled@')) {
        return errorEnvelope(403, 'ACCOUNT_DISABLED', 'This account has been disabled.');
      }
      if (body.password !== 'demo') {
        return errorEnvelope(401, 'INVALID_CREDENTIALS', 'Email or password is incorrect.');
      }
      if (email.startsWith('mfa@') && !body.totpCode) {
        return json({ outcome: 'MFA_REQUIRED', challengeId: 'mock-challenge' });
      }
      const roles = rolesForEmail(email);
      const session = fx.buildSession(email, roles);
      writeDevSessionCookie({
        userId: session.user.userId,
        email: session.user.email,
        displayName: session.user.displayName,
        roles,
        tenantId: session.activeTenant?.tenantId ?? '',
        tenantName: session.activeTenant?.name ?? '',
        tenantCode: session.activeTenant?.tenantCode ?? '',
        syntheticMode: session.activeTenant?.syntheticMode ?? false,
      });
      return json({ outcome: 'AUTHENTICATED', session });
    },
  ],
  [
    /^\/auth\/logout$/,
    'POST',
    () => {
      clearDevSessionCookie();
      return new Response(null, { status: 204 });
    },
  ],
  [
    /^\/auth\/me$/,
    'GET',
    () => {
      const dev = readDevSessionCookie();
      if (!dev) return errorEnvelope(401, 'SESSION_EXPIRED', 'Your session has expired.');
      return json(fx.buildSession(dev.email, dev.roles));
    },
  ],
  [
    /^\/invitations\/preview$/,
    'GET',
    (req) => {
      const token = req.search.get('token');
      if (!token) return errorEnvelope(404, 'INVITATION_NOT_FOUND', 'This invitation link is not valid.');
      if (token === 'expired') {
        return errorEnvelope(410, 'INVITATION_EXPIRED', 'This invitation has expired. Ask your administrator to resend it.');
      }
      return json({
        email: 'new.reviewer@northwind.demo',
        tenantName: 'Northwind Therapeutics',
        invitedByName: 'A. Okafor',
        roles: ['COMPLIANCE_REVIEWER'],
        expiresAt: new Date(Date.now() + 5 * 86400_000).toISOString(),
        mfaRequired: true,
      });
    },
  ],
  [
    /^\/invitations\/accept$/,
    'POST',
    () => {
      const email = 'new.reviewer@northwind.demo';
      const roles = rolesForEmail('compliance@x');
      const session = fx.buildSession(email, roles);
      writeDevSessionCookie({
        userId: session.user.userId,
        email,
        displayName: session.user.displayName,
        roles,
        tenantId: session.activeTenant?.tenantId ?? '',
        tenantName: session.activeTenant?.name ?? '',
        tenantCode: session.activeTenant?.tenantCode ?? '',
        syntheticMode: true,
      });
      return json({ outcome: 'AUTHENTICATED', session });
    },
  ],
  [/^\/data-health\/freshness$/, 'GET', () => json(fx.freshness)],
  [/^\/filter-options$/, 'GET', () => json(fx.filterOptions)],
  [/^\/notifications$/, 'GET', () => json(fx.notifications)],
  [/^\/notifications\/read$/, 'POST', () => new Response(null, { status: 204 })],
  [
    /^\/search$/,
    'GET',
    (req) => {
      const term = (req.search.get('q') ?? '').toLowerCase();
      return json({
        results: fx.searchCorpus.filter(
          (r) => r.title.toLowerCase().includes(term) || (r.subtitle ?? '').toLowerCase().includes(term),
        ),
      });
    },
  ],
  [/^\/saved-views$/, 'GET', () => json({ items: fx.savedViews })],
  [/^\/uploads\/templates$/, 'GET', () => json({ items: fx.uploadTemplates })],
  [/^\/uploads$/, 'GET', () => json(fx.uploadHistory)],
  [/^\/kpis$/, 'GET', () => json({ items: fx.buildKpis() })],
];

let installed = false;

export function installMockApi(): void {
  if (installed || !env.apiMock) return;
  installed = true;

  const original = globalThis.fetch.bind(globalThis);

  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const rawUrl =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;

    // Resolve against a placeholder origin so relative paths parse. The origin
    // is discarded; only the pathname is matched.
    const url = new URL(rawUrl, 'http://mock.local');
    if (!url.pathname.startsWith(env.apiBaseUrl)) return original(input, init);

    const path = url.pathname.slice(env.apiBaseUrl.length) || '/';
    const method = (init?.method ?? (typeof input === 'object' && 'method' in input ? input.method : 'GET') ?? 'GET').toUpperCase();

    let body: unknown;
    if (typeof init?.body === 'string') {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    }

    for (const [pattern, verb, handler] of routes) {
      if (verb === method && pattern.test(path)) {
        // A little latency so skeletons and progress states are actually
        // visible during visual review instead of flashing.
        await new Promise((resolve) => setTimeout(resolve, 180));
        return handler({ method, path, search: url.searchParams, body });
      }
    }

    // Unimplemented endpoint: answer with the real envelope so the UI's error
    // states are exercised rather than silently hanging.
    return errorEnvelope(
      501,
      'MOCK_NOT_IMPLEMENTED',
      `No mock handler for ${method} ${path}. Add one in src/lib/api/mock/index.ts.`,
    );
  };
}

export { DEMO_LOGINS } from './session';
