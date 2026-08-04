'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  listRetentionPolicies,
  previewPurge,
  purgeDataset,
  setRetentionPolicy,
} from '@/features/retention/api';
import type { RetentionDataset } from '@/features/retention/schema';
import { logKeys } from '@/features/logs/hooks/use-logs';
import { usageKeys } from '@/features/usage/hooks/use-usage';

export const retentionKeys = {
  all: ['retention'] as const,
  preview: (dataset: RetentionDataset, days: number | undefined) =>
    [...retentionKeys.all, 'preview', dataset, days ?? 'stored'] as const,
};

export function useRetentionPolicies() {
  return useQuery({ queryKey: retentionKeys.all, queryFn: listRetentionPolicies });
}

/**
 * The count for a window the form is holding but has not saved.
 *
 * `enabled` rather than a conditional hook, and keyed by the window, so typing
 * 90 and then 120 asks twice and caches both instead of showing the first
 * answer under the second number.
 */
export function usePurgePreview(
  dataset: RetentionDataset,
  days: number | undefined,
  enabled: boolean,
) {
  return useQuery({
    queryKey: retentionKeys.preview(dataset, days),
    queryFn: () => previewPurge(dataset, days),
    enabled,
    staleTime: 30_000,
  });
}

export function useSetRetentionPolicy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ dataset, days }: { dataset: RetentionDataset; days: number }) =>
      setRetentionPolicy(dataset, days),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: retentionKeys.all });
    },
  });
}

export function usePurgeDataset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ dataset, days }: { dataset: RetentionDataset; days?: number }) =>
      purgeDataset(dataset, days),
    onSuccess: () => {
      // The two screens that read what was just deleted. Without this the logs
      // table keeps showing rows that no longer exist until something else
      // refetches, which reads as a purge that did not work.
      void client.invalidateQueries({ queryKey: retentionKeys.all });
      void client.invalidateQueries({ queryKey: logKeys.all });
      void client.invalidateQueries({ queryKey: usageKeys.all });
    },
  });
}
