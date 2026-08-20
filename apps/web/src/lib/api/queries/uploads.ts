'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from '../client';
import { qk, type FilterKey } from '../queryKeys';
import { STALE } from '../queryClient';
import {
  paginatedSchema,
  uploadBatchSchema,
  uploadSessionSchema,
  uploadTemplateSchema,
  type DatasetType,
  type Paginated,
  type UploadBatch,
  type UploadSession,
  type UploadTemplate,
} from '../types';
import { isTerminalUploadStatus } from '../enums';

const templateList = z.object({ items: z.array(uploadTemplateSchema) });
const uploadPage = paginatedSchema(uploadBatchSchema);

export function useUploadTemplates(tenantId: string | null) {
  return useQuery({
    queryKey: qk.uploads.templates(tenantId ?? 'none'),
    queryFn: () =>
      api.get<{ items: UploadTemplate[] }>('/uploads/templates', { schema: templateList }),
    enabled: Boolean(tenantId),
    staleTime: STALE.reference,
  });
}

export function useUploadHistory(tenantId: string | null, filters: FilterKey) {
  return useQuery({
    queryKey: qk.uploads.list(tenantId ?? 'none', filters),
    queryFn: () =>
      api.get<Paginated<UploadBatch>>('/uploads', {
        query: filters as Record<string, string>,
        schema: uploadPage,
      }),
    enabled: Boolean(tenantId),
    staleTime: STALE.operational,
  });
}

/**
 * Polls one batch while it is in flight.
 *
 * The interval is driven by `isTerminalUploadStatus` rather than a fixed number
 * of attempts: a 200k-row conformance pass can take minutes, and a poller that
 * gives up leaves the user staring at "VALIDATING" forever. Once terminal, the
 * interval returns false and polling stops for good.
 */
export function useUploadBatch(tenantId: string | null, uploadId: string | null) {
  return useQuery({
    queryKey: qk.uploads.detail(tenantId ?? 'none', uploadId ?? 'none'),
    queryFn: () =>
      api.get<UploadBatch>(`/uploads/${uploadId}`, { schema: uploadBatchSchema }),
    enabled: Boolean(tenantId && uploadId),
    staleTime: STALE.none,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status) return 2_000;
      return isTerminalUploadStatus(status) ? false : 2_000;
    },
  });
}

export interface CreateUploadSessionInput {
  datasetType: DatasetType;
  fileName: string;
  sizeBytes: number;
  contentType: string;
  /** Permitted scope selected in the dropzone (plan.md §10.3 step 2). */
  brandId?: string;
  campaignId?: string;
  eventId?: string;
}

export function useCreateUploadSession() {
  return useMutation({
    mutationFn: (input: CreateUploadSessionInput) =>
      api.post<UploadSession>('/uploads/sessions', input, { schema: uploadSessionSchema }),
  });
}

/** Step 7 of plan.md §10.3 — bytes have landed, ask the worker to process. */
export function useConfirmUpload(tenantId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (uploadId: string) =>
      api.post<UploadBatch>(`/uploads/${uploadId}/confirm`, undefined, {
        schema: uploadBatchSchema,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: qk.uploads.all(tenantId ?? 'none') }),
  });
}

export function useRetryUpload(tenantId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (uploadId: string) =>
      api.post<UploadBatch>(`/uploads/${uploadId}/retry`, undefined, {
        schema: uploadBatchSchema,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: qk.uploads.all(tenantId ?? 'none') }),
  });
}
