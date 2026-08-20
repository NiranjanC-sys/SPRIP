'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../client';
import { qk } from '../queryKeys';
import { STALE } from '../queryClient';
import {
  filterOptionsSchema,
  freshnessSchema,
  notificationSchema,
  paginatedSchema,
  savedViewSchema,
  searchResultSchema,
  type FilterOptions,
  type Freshness,
  type NotificationItem,
  type Paginated,
  type SavedView,
  type SearchResult,
} from '../types';
import { z } from 'zod';

/** Drives the top-bar freshness indicator. Short staleTime: it is the one
 *  number on screen whose job is to be current. */
export function useFreshness(tenantId: string | null) {
  return useQuery({
    queryKey: qk.tenant.freshness(tenantId ?? 'none'),
    queryFn: () => api.get<Freshness>('/data-health/freshness', { schema: freshnessSchema }),
    enabled: Boolean(tenantId),
    staleTime: STALE.operational,
    refetchOnWindowFocus: true,
  });
}

/** Populates every FilterBar. Reference data, so it caches hard. */
export function useFilterOptions(tenantId: string | null) {
  return useQuery({
    queryKey: qk.tenant.filterOptions(tenantId ?? 'none'),
    queryFn: () => api.get<FilterOptions>('/filter-options', { schema: filterOptionsSchema }),
    enabled: Boolean(tenantId),
    staleTime: STALE.reference,
  });
}

const notificationPage = paginatedSchema(notificationSchema);

export function useNotifications(unreadOnly = false) {
  return useQuery({
    queryKey: qk.notifications.list(unreadOnly),
    queryFn: () =>
      api.get<Paginated<NotificationItem>>('/notifications', {
        query: { unreadOnly },
        schema: notificationPage,
      }),
    staleTime: STALE.operational,
  });
}

export function useMarkNotificationsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => api.post<void>('/notifications/read', { notificationIds: ids }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.notifications.all() }),
  });
}

const searchResults = z.object({ results: z.array(searchResultSchema) });

/**
 * Command-palette search. Server-side because the palette must never surface an
 * entity the user is not scoped to — filtering a client-side index would leak
 * the *existence* of out-of-scope events.
 */
export function useEntitySearch(term: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.search(term),
    queryFn: () =>
      api.get<{ results: SearchResult[] }>('/search', {
        query: { q: term, limit: 12 },
        schema: searchResults,
      }),
    enabled: enabled && term.trim().length >= 2,
    staleTime: STALE.operational,
  });
}

const savedViewList = z.object({ items: z.array(savedViewSchema) });

export function useSavedViews(tenantId: string | null, scope: string) {
  return useQuery({
    queryKey: qk.savedViews.byScope(tenantId ?? 'none', scope),
    queryFn: () =>
      api.get<{ items: SavedView[] }>('/saved-views', { query: { scope }, schema: savedViewList }),
    enabled: Boolean(tenantId),
    staleTime: STALE.reference,
  });
}

export interface CreateSavedViewInput {
  name: string;
  scope: string;
  query: string;
  isShared: boolean;
}

export function useCreateSavedView(tenantId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateSavedViewInput) =>
      api.post<SavedView>('/saved-views', input, { schema: savedViewSchema }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: qk.savedViews.all(tenantId ?? 'none') }),
  });
}

export function useDeleteSavedView(tenantId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (savedViewId: string) => api.delete<void>(`/saved-views/${savedViewId}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: qk.savedViews.all(tenantId ?? 'none') }),
  });
}
