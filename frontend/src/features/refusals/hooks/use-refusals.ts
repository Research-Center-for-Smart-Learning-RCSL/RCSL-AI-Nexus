'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { listRefusals } from '@/features/refusals/api';
import type { RefusalFilters } from '@/features/refusals/schema';

export const refusalKeys = {
  all: ['refusals'] as const,
  page: (filters: RefusalFilters) => [...refusalKeys.all, 'page', filters] as const,
};

/**
 * Server-paged, like the audit log and the transcripts, and for the same
 * reason: the table is append-only and anyone with a key can add to it.
 *
 * `staleTime` is short because the question this screen answers is usually
 * about something that just happened — somebody is looking at it *because* a
 * request failed a minute ago, and a five-minute cache would show them a page
 * that does not contain it yet.
 */
export function useRefusals(filters: RefusalFilters) {
  return useQuery({
    queryKey: refusalKeys.page(filters),
    queryFn: () => listRefusals(filters),
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });
}
