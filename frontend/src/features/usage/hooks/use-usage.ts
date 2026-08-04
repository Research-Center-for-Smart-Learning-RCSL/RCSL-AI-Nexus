'use client';

import { useQuery } from '@tanstack/react-query';

import { getOwnUsage, getUsage } from '@/features/usage/api';
import type { UsageRange } from '@/features/usage/schema';

export const usageKeys = {
  all: ['usage'] as const,
  range: (range: UsageRange) => [...usageKeys.all, range] as const,
  /**
   * Deliberately a different key, not a flag inside the same one. The two
   * endpoints return the same shape over different rows, so a shared cache
   * entry would let one answer be served for the other question — and the
   * narrower one arriving first would look exactly like a quiet platform.
   */
  own: (range: UsageRange) => [...usageKeys.all, 'me', range] as const,
};

/**
 * A minute of staleness matches the accounting nature of the source: these are
 * usage_records aggregates, not the live operational metrics Grafana shows, so
 * there is no reason to poll harder than the dashboard totals do.
 *
 * `mine` selects the endpoint rather than filtering what came back, and is one
 * `useQuery` rather than two hooks behind a condition, which the rules of hooks
 * would not allow the caller to choose between anyway.
 */
export function useUsage(range: UsageRange, { mine = false }: { mine?: boolean } = {}) {
  return useQuery({
    queryKey: mine ? usageKeys.own(range) : usageKeys.range(range),
    queryFn: () => (mine ? getOwnUsage(range) : getUsage(range)),
    staleTime: 60_000,
  });
}
