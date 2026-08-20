'use client';

import * as React from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { qk } from '@/lib/api/queryKeys';
import type { Session } from '@/lib/api/types';

/**
 * Seeds the client cache with the session the server layout already resolved.
 *
 * Without this, every page mounts, calls `useSession()`, and waits a round trip
 * for an answer the server rendered with — so every page header, nav rail and
 * tenant switcher flashes a skeleton on first paint of a hard navigation.
 *
 * Written during the first render rather than in an effect: effects run *after*
 * paint, which is exactly the frame we are trying to fix. This is the same shape
 * TanStack's own `HydrationBoundary` uses.
 */
export function SessionBoundary({
  session,
  children,
}: {
  session: Session;
  children: React.ReactNode;
}) {
  const queryClient = useQueryClient();
  const seeded = React.useRef(false);

  if (!seeded.current) {
    seeded.current = true;
    queryClient.setQueryData(qk.session(), session);
  }

  return <>{children}</>;
}
