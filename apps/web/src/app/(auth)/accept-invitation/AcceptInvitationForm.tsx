'use client';

import * as React from 'react';
import { AlertCircle, Check, KeyRound, ShieldCheck, X } from 'lucide-react';

import { ApiError } from '@/lib/api/errors';
import { landingRouteForRoles } from '@/lib/api/enums';
import { useAcceptInvitation, useInvitationPreview } from '@/lib/api/queries/session';
import { formatDate } from '@/lib/formatters';
import { humanizeEnum } from '@/lib/utils';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Callout } from '@/components/ui/callout';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';

/**
 * Invitation acceptance — the only way an account comes into existence.
 *
 * The token is previewed before anything is typed so the user can see which
 * organisation invited them and with what roles. Accepting an invitation to the
 * wrong tenant is not recoverable by the user, and "Northwind Therapeutics
 * invited you as a Compliance Reviewer" is the sentence that prevents it.
 *
 * Password policy is enforced client-side *and* server-side. This list exists to
 * make the rules visible while typing rather than as a wall of red after submit;
 * the server remains the authority.
 */

interface Rule {
  id: string;
  label: string;
  test: (value: string) => boolean;
}

/**
 * NIST SP 800-63B: length carries the strength, composition rules do not. The
 * one composition rule kept is a mixed-character check, because tenant security
 * policies still require it in every pharma procurement questionnaire we answer.
 */
const MIN_PASSWORD_LENGTH = 12;

const RULES: readonly Rule[] = [
  {
    id: 'length',
    label: `At least ${MIN_PASSWORD_LENGTH} characters`,
    test: (v) => v.length >= MIN_PASSWORD_LENGTH,
  },
  { id: 'case', label: 'Upper and lower case letters', test: (v) => /[a-z]/.test(v) && /[A-Z]/.test(v) },
  { id: 'other', label: 'A number or a symbol', test: (v) => /[^A-Za-z]/.test(v) },
];

const TOTP_LENGTH = 6;

export function AcceptInvitationForm({ token }: { token: string | null }) {
  const preview = useInvitationPreview(token);
  const accept = useAcceptInvitation();

  const [password, setPassword] = React.useState('');
  const [confirm, setConfirm] = React.useState('');
  const [totpCode, setTotpCode] = React.useState('');
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  if (!token) {
    return (
      <Alert tone="danger" title="This link is incomplete">
        The invitation link is missing its token. Use the full link from the email exactly as it was
        sent — some mail clients truncate long URLs.
      </Alert>
    );
  }

  if (preview.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-56" label="Checking invitation" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    );
  }

  if (preview.isError || !preview.data) {
    const expired = preview.error instanceof ApiError && preview.error.code === 'INVITATION_EXPIRED';
    return (
      <Alert
        tone={expired ? 'warning' : 'danger'}
        title={expired ? 'This invitation has expired' : 'This invitation is not valid'}
      >
        {expired
          ? 'Invitations are time-limited. Ask the person who invited you to send a new one.'
          : 'The link may have already been used, or been withdrawn. Ask your administrator to resend it.'}
      </Alert>
    );
  }

  const invitation = preview.data;
  const rulesPassed = RULES.filter((r) => r.test(password));

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (rulesPassed.length < RULES.length) next['password'] = 'This password does not meet the policy.';
    // Compared rather than hidden behind a "show password" toggle: a mistyped
    // password on the account-creation step locks a brand-new user out entirely.
    if (password !== confirm) next['confirm'] = 'The two passwords do not match.';
    if (invitation.mfaRequired && totpCode.trim().length < TOTP_LENGTH) {
      next['totp'] = `Enter the ${TOTP_LENGTH}-digit code from your authenticator app.`;
    }
    setFieldErrors(next);
    if (Object.keys(next).length > 0) return;

    accept.mutate(
      {
        token: token as string,
        password,
        ...(invitation.mfaRequired ? { totpCode: totpCode.trim() } : {}),
      },
      {
        onSuccess: (result) => {
          if (result.outcome === 'AUTHENTICATED') {
            // Full navigation: the session cookie is brand new and every server
            // component above cached the anonymous answer.
            window.location.assign(landingRouteForRoles(result.session.roles));
          }
        },
      },
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-display font-semibold tracking-tight text-text">Set up your account</h1>
        <p className="text-sm leading-relaxed text-text-muted">
          <span className="font-medium text-text">{invitation.invitedByName}</span> invited you to{' '}
          <span className="font-medium text-text">{invitation.tenantName}</span>.
        </p>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-sunken p-3">
        <Row label="Email">
          <span className="font-medium text-text">{invitation.email}</span>
        </Row>
        <Row label="Roles">
          <span className="flex flex-wrap gap-1">
            {invitation.roles.map((role) => (
              <Badge key={role} variant="outline">
                {humanizeEnum(role)}
              </Badge>
            ))}
          </span>
        </Row>
        <Row label="Expires">{formatDate(invitation.expiresAt)}</Row>
      </div>

      {accept.isError ? (
        <Alert tone="danger" title="Could not complete setup">
          {accept.error instanceof ApiError
            ? accept.error.message
            : 'Something went wrong. Try again.'}
        </Alert>
      ) : null}

      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        <FormField label="Choose a password" error={fieldErrors['password'] ?? null} required>
          <Input
            name="new-password"
            type="password"
            autoComplete="new-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </FormField>

        <ul className="flex flex-col gap-1" aria-label="Password requirements">
          {RULES.map((rule) => {
            const ok = rule.test(password);
            return (
              <li
                key={rule.id}
                className={`flex items-center gap-1.5 text-xs ${ok ? 'text-positive' : 'text-text-subtle'}`}
              >
                {/* The icon is decorative; the text and the colour both carry the
                    state, so colour is never the only channel (WCAG 1.4.1). */}
                <span aria-hidden="true">
                  {ok ? <Check className="size-3.5" /> : <X className="size-3.5" />}
                </span>
                <span>
                  {rule.label}
                  <span className="sr-only">{ok ? ' — met' : ' — not yet met'}</span>
                </span>
              </li>
            );
          })}
        </ul>

        <FormField label="Confirm password" error={fieldErrors['confirm'] ?? null} required>
          <Input
            name="confirm-password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </FormField>

        {invitation.mfaRequired ? (
          <>
            <Callout tone="info" icon={<ShieldCheck />}>
              This organisation requires two-factor authentication. Scan the enrolment QR code shown
              after setup, or enter a code now if you have already enrolled this account.
            </Callout>
            <FormField
              label="Verification code"
              error={fieldErrors['totp'] ?? null}
              hint={`${TOTP_LENGTH} digits from your authenticator app.`}
              required
            >
              <Input
                name="totp"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={TOTP_LENGTH}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, TOTP_LENGTH))}
                iconLeft={<KeyRound />}
                className="font-mono tracking-[0.35em]"
              />
            </FormField>
          </>
        ) : null}

        <Button type="submit" size="lg" block loading={accept.isPending} loadingLabel="Creating account">
          Create account and sign in
        </Button>
      </form>

      <p className="flex items-start gap-1.5 text-xs leading-relaxed text-text-subtle">
        <AlertCircle aria-hidden="true" className="mt-px size-3.5 shrink-0" />
        <span>
          Do not share this link. Anyone who opens it before you do can claim this account.
        </span>
      </p>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 text-xs">
      <span className="shrink-0 text-text-subtle">{label}</span>
      <span className="min-w-0 text-right text-text-muted">{children}</span>
    </div>
  );
}
