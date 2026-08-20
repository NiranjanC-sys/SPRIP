'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, Building2, Eye, EyeOff, KeyRound, Mail, ShieldCheck } from 'lucide-react';

import { AuthProviderKind, landingRouteForRoles, type Role } from '@/lib/api/enums';
import { ApiError, NetworkError } from '@/lib/api/errors';
import { useLogin } from '@/lib/api/queries/session';
import { env } from '@/lib/env';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Callout } from '@/components/ui/callout';
import { FormField } from '@/components/ui/form-field';
import { IconButton } from '@/components/ui/icon-button';
import { Input } from '@/components/ui/input';

/**
 * The sign-in form.
 *
 * Two providers, one component. Which one is live is a *build-time* decision
 * (`NEXT_PUBLIC_AUTH_PROVIDER`), not a user choice: offering "or sign in with a
 * password" next to corporate SSO in an enterprise that mandates SSO is how
 * shadow local accounts survive an audit.
 *
 * There is no self-signup and no "create an account" link anywhere — access is
 * invite-only (plan.md §5.3). The password-reset affordance is deliberately a
 * contact instruction rather than a self-service link, because the reset flow is
 * owned by the tenant's administrator, not by this screen.
 */

/** RFC 6238 default. Named so the field, the hint and the check cannot disagree. */
const TOTP_LENGTH = 6;

interface FailureCopy {
  title: string;
  body: string;
  /** Locked and disabled accounts are terminal — hide the form, do not invite retries. */
  terminal?: boolean;
}

/**
 * Server error code → what the user is told.
 *
 * `INVALID_CREDENTIALS` intentionally does not distinguish "no such user" from
 * "wrong password": the difference is a user-enumeration oracle, and for a
 * closed tenant the mere existence of an address is commercially interesting.
 */
const FAILURES: Readonly<Record<string, FailureCopy>> = {
  INVALID_CREDENTIALS: {
    title: 'Email or password is incorrect',
    body: 'Check the address and try again. Repeated failures will lock the account.',
  },
  ACCOUNT_LOCKED: {
    title: 'This account is locked',
    body: 'Too many failed attempts, or an administrator locked it. Your organisation administrator can unlock it.',
    terminal: true,
  },
  ACCOUNT_DISABLED: {
    title: 'This account is no longer active',
    body: 'Access was withdrawn. If this is unexpected, contact your organisation administrator.',
    terminal: true,
  },
  TENANT_SUSPENDED: {
    title: 'This workspace is suspended',
    body: 'Your organisation’s access is on hold. Contact your account manager — no data has been deleted.',
    terminal: true,
  },
  MFA_INVALID: {
    title: 'That verification code did not match',
    body: 'Codes expire every 30 seconds. Wait for the next one and enter it again.',
  },
  RATE_LIMITED: {
    title: 'Too many attempts',
    body: 'Wait a minute before trying again.',
  },
};

function failureFor(error: unknown): FailureCopy {
  if (error instanceof NetworkError) {
    return {
      title: 'Cannot reach the sign-in service',
      body: 'Check your network connection. If you are on a corporate VPN, confirm it is connected.',
    };
  }
  if (error instanceof ApiError) {
    const known = FAILURES[error.code];
    if (known) return known;
    return { title: 'Sign-in failed', body: error.message };
  }
  return { title: 'Sign-in failed', body: 'Something went wrong. Try again.' };
}

export interface LoginFormProps {
  /** Already validated as same-origin and path-only by the server component. */
  returnTo: string | null;
  /** Set when the middleware bounced an expired session here. */
  reason: string | null;
}

export function LoginForm({ returnTo, reason }: LoginFormProps) {
  const router = useRouter();
  const login = useLogin();

  const [email, setEmail] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [totpCode, setTotpCode] = React.useState('');
  const [showPassword, setShowPassword] = React.useState(false);
  const [challengeId, setChallengeId] = React.useState<string | null>(null);
  /** Client-side validation, keyed by field so the message lands on the control. */
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  const totpRef = React.useRef<HTMLInputElement>(null);
  const isOidc = env.authProvider === AuthProviderKind.OIDC;

  // Move focus to the code field the moment the challenge appears. Without this
  // the user retypes their password into the box that just replaced it.
  React.useEffect(() => {
    if (challengeId) totpRef.current?.focus();
  }, [challengeId]);

  const failure = login.error ? failureFor(login.error) : null;

  function goAfterLogin(roles: readonly Role[]) {
    // `returnTo` wins so a deep link survives the round trip; the role landing
    // route is the fallback. Both are internal paths — never a full URL.
    const target = returnTo ?? landingRouteForRoles(roles);
    // A full navigation, not `router.push`: the session cookie was just set and
    // every server component above this point cached the anonymous answer.
    window.location.assign(target);
  }

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // Validate everything before returning, so a user missing both fields is told
    // about both rather than being walked through one error per submit.
    const next: Record<string, string> = {};
    if (challengeId) {
      if (totpCode.trim().length < TOTP_LENGTH) {
        next['totp'] = `Enter the ${TOTP_LENGTH}-digit code from your authenticator app.`;
      }
    } else {
      if (!email.trim()) next['email'] = 'Enter your work email address.';
      if (!password) next['password'] = 'Enter your password.';
    }
    setFieldErrors(next);
    if (Object.keys(next).length > 0) return;

    login.mutate(
      {
        email: email.trim(),
        password,
        ...(challengeId ? { challengeId, totpCode: totpCode.trim() } : {}),
      },
      {
        onSuccess: (result) => {
          switch (result.outcome) {
            case 'AUTHENTICATED':
              goAfterLogin(result.session.roles);
              return;
            case 'MFA_REQUIRED':
              setChallengeId(result.challengeId);
              return;
            case 'PASSWORD_RESET_REQUIRED':
              router.push(`/accept-invitation?token=${encodeURIComponent(result.resetToken)}&mode=reset`);
              return;
            case 'REDIRECT':
              // Only the API decides this URL; it is an external IdP endpoint by
              // definition, so `assign` rather than the router.
              window.location.assign(result.authorizationUrl);
              return;
          }
        },
      },
    );
  }

  /* --- OIDC: one button, nothing to type ---------------------------------- */

  if (isOidc) {
    const authorizeUrl = `${env.apiBaseUrl}/auth/oidc/authorize${
      returnTo ? `?returnTo=${encodeURIComponent(returnTo)}` : ''
    }`;
    return (
      <div className="flex flex-col gap-6">
        <Header reason={reason} />
        <Button asChild size="lg" block iconLeft={<Building2 />} iconRight={<ArrowRight />}>
          {/* A real anchor, not a fetch: the authorization endpoint issues a 302 to
              the IdP, and an XHR would follow it invisibly and fail CORS. */}
          <a href={authorizeUrl}>Continue with {env.oidcDisplayName}</a>
        </Button>
        <Callout icon={<ShieldCheck />}>
          You will be redirected to your organisation&apos;s identity provider. Roles and workspace
          access are resolved here after you return — group membership alone does not grant access.
        </Callout>
      </div>
    );
  }

  /* --- local: email + password, then TOTP if challenged ------------------- */

  return (
    <div className="flex flex-col gap-6">
      <Header reason={reason} />

      {failure ? (
        <Alert tone={failure.terminal ? 'warning' : 'danger'} title={failure.title}>
          {failure.body}
        </Alert>
      ) : null}

      {failure?.terminal ? null : (
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          {challengeId ? (
            <>
              <FormField
                label="Verification code"
                hint={`${TOTP_LENGTH} digits from your authenticator app.`}
                error={fieldErrors['totp'] ?? null}
                required
              >
                <Input
                  ref={totpRef}
                  name="totp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  // Digits are stripped on change and the length is capped, so a
                  // pasted "123 456" is normalised here rather than bouncing off
                  // the server a round trip later.
                  pattern="[0-9]*"
                  maxLength={TOTP_LENGTH}
                  placeholder={'0'.repeat(TOTP_LENGTH)}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, TOTP_LENGTH))}
                  iconLeft={<KeyRound />}
                  className="font-mono tracking-[0.35em]"
                />
              </FormField>

              <Button type="submit" size="lg" block loading={login.isPending} loadingLabel="Verifying">
                Verify and sign in
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setChallengeId(null);
                  setTotpCode('');
                  login.reset();
                }}
              >
                Use a different account
              </Button>
            </>
          ) : (
            <>
              <FormField label="Work email" error={fieldErrors['email'] ?? null} required>
                <Input
                  name="email"
                  type="email"
                  autoComplete="username"
                  autoFocus
                  spellCheck={false}
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  iconLeft={<Mail />}
                />
              </FormField>

              <FormField
                label="Password"
                required
                error={fieldErrors['password'] ?? null}
                labelSuffix={
                  <span className="text-2xs text-text-subtle">Forgotten? Ask your administrator</span>
                }
              >
                <Input
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  slotRight={
                    <IconButton
                      type="button"
                      variant="ghost"
                      size="sm"
                      // The label states the *result* of pressing it, which is what
                      // a screen-reader user needs — not the current state.
                      label={showPassword ? 'Hide password' : 'Show password'}
                      onClick={() => setShowPassword((v) => !v)}
                    >
                      {showPassword ? <EyeOff /> : <Eye />}
                    </IconButton>
                  }
                />
              </FormField>

              <Button type="submit" size="lg" block loading={login.isPending} loadingLabel="Signing in">
                Sign in
              </Button>
            </>
          )}
        </form>
      )}

      <p className="text-xs leading-relaxed text-text-subtle">
        Accounts are created by invitation only. If you need access, ask your organisation
        administrator to invite you.
      </p>

      {env.apiMock ? <DemoHint /> : null}
    </div>
  );
}

function Header({ reason }: { reason: string | null }) {
  return (
    <div className="flex flex-col gap-2">
      <h1 className="text-display font-semibold tracking-tight text-text">Sign in</h1>
      <p className="text-sm leading-relaxed text-text-muted">
        Speaker programme impact and return on investment.
      </p>
      {reason === 'expired' ? (
        <Alert tone="info" title="Your session ended" className="mt-2">
          Sessions expire after a period of inactivity. Sign in again to continue where you left off.
        </Alert>
      ) : null}
    </div>
  );
}

/** Dev fixture affordance. Folded out of the bundle when the flag is off. */
function DemoHint() {
  return (
    <Callout tone="info">
      Fixture mode. Any of <code className="font-mono">analytics@</code>,{' '}
      <code className="font-mono">finance@</code>, <code className="font-mono">vendor@</code>,{' '}
      <code className="font-mono">compliance@</code>, <code className="font-mono">steward@</code>,{' '}
      <code className="font-mono">admin@</code>, <code className="font-mono">platform@</code>{' '}
      <code className="font-mono">northwind.demo</code> with password{' '}
      <code className="font-mono">demo</code>. Prefix with <code className="font-mono">mfa@</code>,{' '}
      <code className="font-mono">locked@</code> or <code className="font-mono">disabled@</code> to
      exercise those branches.
    </Callout>
  );
}
