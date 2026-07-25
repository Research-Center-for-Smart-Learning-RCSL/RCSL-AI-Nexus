'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { getLogs } from '@/features/logs/api';
import type { LogFilters } from '@/features/logs/schema';

export const logKeys = {
  all: ['logs'] as const,
  page: (filters: LogFilters) => [...logKeys.all, filters] as const,
};

/**
 * Server-paged, because the audit log is append-only and grows without bound, so
 * a client-side table over the whole thing is the wrong shape. `keepPreviousData`
 * holds the current page visible while the next one loads, so paging does not
 * flash empty.
 */
export function useLogs(filters: LogFilters) {
  return useQuery({
    queryKey: logKeys.page(filters),
    queryFn: () => getLogs(filters),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}
