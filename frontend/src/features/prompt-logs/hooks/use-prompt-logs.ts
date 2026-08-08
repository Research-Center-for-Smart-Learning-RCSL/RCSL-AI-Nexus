'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { getPromptLogTranscript, listPromptLogs } from '@/features/prompt-logs/api';
import type { PromptLogFilters } from '@/features/prompt-logs/schema';

export const promptLogKeys = {
  all: ['prompt-logs'] as const,
  page: (filters: PromptLogFilters) => [...promptLogKeys.all, 'page', filters] as const,
  transcript: (id: string) => [...promptLogKeys.all, 'transcript', id] as const,
};

/** Server-paged, like the audit log and for the same reason. */
export function usePromptLogs(filters: PromptLogFilters) {
  return useQuery({
    queryKey: promptLogKeys.page(filters),
    queryFn: () => listPromptLogs(filters),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

/**
 * One transcript, fetched only once an operator has asked for it.
 *
 * Three settings here are about the audit trail rather than about performance,
 * because this request writes a `prompt_log.read` row every time it is made:
 *
 * - `enabled` gates it on an id, so nothing is fetched until a row is opened;
 * - `staleTime: Infinity` means reopening the same transcript in one session
 *   does not record a second read, which would otherwise turn one operator
 *   glancing twice into two entries;
 * - refetch on focus and on mount are off, so leaving the tab and coming back
 *   does not write a row nobody asked for.
 *
 * The trail should say "this person read this conversation", and each entry
 * should correspond to a decision somebody made. A record produced by window
 * management describes nothing.
 *
 * A transcript is immutable once written, so none of this risks staleness.
 */
export function usePromptLogTranscript(id: string | null) {
  return useQuery({
    queryKey: promptLogKeys.transcript(id ?? ''),
    queryFn: () => getPromptLogTranscript(id as string),
    enabled: id !== null,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    retry: false,
  });
}
