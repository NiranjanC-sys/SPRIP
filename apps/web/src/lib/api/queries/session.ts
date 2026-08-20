'use client';

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import { api, resetSessionExpiredLatch } from '../client';
import { UnauthorizedError } from '../errors';
import { qk } from '../queryKeys';
import { STALE } from '../queryClient';
import {
  invitationPreviewSchema,
  loginResultSchema,
  sessionSchema,
  type InvitationPreview,
  type LoginResult,
  type Session,
} from '../types';

/**
 * The session hook every client component uses.
 *
 * A 401 resolves to `null` rather than throwing: the shell only ever renders
 * behind middleware, so a null session here means "the cookie died while the
 * tab was open", and the client wrapper has already started the redirect. Making
 * that an error would additionally paint an error boundary over a page that is
 * about to navigate away.
 */
export function useSession(): UseQueryResult<Session | null> {
  return useQuery({
    queryKey: qk.session(),
    queryFn: async () => {
      try {
        return await api.get<Session>('/auth/me', {
          schema: sessionSchema,
          suppressAuthRedirect: true,
        });
      } catch (error) {
        if (error instanceof UnauthorizedError) return null;
        throw error;
      }
    },
    staleTime: STALE.session,
    // A role revoked by an admin should stop rendering privileged nav within a
    // tab focus, not on next full reload.
    refetchOnWindowFocus: true,
    retry: false,
  });
}

/**
 * Convenience for components that are unconditionally inside the shell. Returns
 * a definitely-present session or throws, so callers stop writing `session?.`
 * chains that hide a real bug behind optional chaining.
 */
export function useRequiredSession(): Session {
  const { data } = useSession();
  if (!data) {
    throw new Error(
      'useRequiredSession() called outside an authenticated shell. Wrap the tree in <SessionProvider> under (app).',
    );
  }
  return data;
}

export interface LocalLoginInput {
  email: string;
  password: string;
  /** Present only on the second leg of an MFA challenge. */
  totpCode?: string;
  challengeId?: string;
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation<LoginResult, unknown, LocalLoginInput>({
    mutationFn: (input) =>
      api.post<LoginResult>('/auth/login', input, {
        schema: loginResultSchema,
        // The form renders "invalid credentials" itself; a redirect here would
        // bounce the user off the page they are typing into.
        suppressAuthRedirect: true,
        idempotencyKey: undefined,
      }),
    onSuccess: (result) => {
      if (result.outcome === 'AUTHENTICATED') {
        resetSessionExpiredLatch();
        queryClient.setQueryData(qk.session(), result.session);
      }
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>('/auth/logout'),
    onSettled: () => {
      // Clear unconditionally. If logout failed server-side the cookie may still
      // be live, but leaving another user's tenant data in an in-memory cache on
      // a shared workstation is the worse outcome.
      queryClient.clear();
    },
  });
}

export function useInvitationPreview(token: string | null) {
  return useQuery({
    queryKey: ['invitation', token],
    queryFn: () =>
      api.get<InvitationPreview>('/invitations/preview', {
        query: { token: token ?? '' },
        schema: invitationPreviewSchema,
        suppressAuthRedirect: true,
      }),
    enabled: Boolean(token),
    staleTime: STALE.none,
    retry: false,
  });
}

export interface AcceptInvitationInput {
  token: string;
  password: string;
  /** Present when the tenant requires TOTP enrolment at acceptance. */
  totpSecret?: string;
  totpCode?: string;
}

export function useAcceptInvitation() {
  return useMutation<LoginResult, unknown, AcceptInvitationInput>({
    mutationFn: (input) =>
      api.post<LoginResult>('/invitations/accept', input, {
        schema: loginResultSchema,
        suppressAuthRedirect: true,
      }),
  });
}
