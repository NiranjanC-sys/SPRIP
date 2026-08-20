import { AuthProviderKind } from '@/lib/api/enums';

/**
 * Public configuration, read once.
 *
 * Next.js inlines `process.env.NEXT_PUBLIC_*` at build time only when the
 * property is accessed literally — `process.env[key]` is not substituted. Every
 * read below is therefore written out longhand, which is also what lets the
 * bundler drop the mock module when the flag is off.
 */

function readAuthProvider(): AuthProviderKind {
  const raw = (process.env.NEXT_PUBLIC_AUTH_PROVIDER ?? 'local').toUpperCase();
  return raw === AuthProviderKind.OIDC ? AuthProviderKind.OIDC : AuthProviderKind.LOCAL;
}

export const env = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? '/api/v1',
  authProvider: readAuthProvider(),
  oidcDisplayName: process.env.NEXT_PUBLIC_OIDC_DISPLAY_NAME ?? 'corporate identity',
  environmentLabel: process.env.NEXT_PUBLIC_ENVIRONMENT_LABEL ?? '',
  /**
   * Dev-only fixture mode. Deliberately compared against the literal '1' so a
   * stray `NEXT_PUBLIC_API_MOCK=false` cannot enable it, and so the comparison
   * folds to `false` at build time and the mock module tree-shakes away.
   */
  apiMock: process.env.NEXT_PUBLIC_API_MOCK === '1',
} as const;

export const isProductionBuild = process.env.NODE_ENV === 'production';
