'use client';

import { useQuery } from '@tanstack/react-query';

import { getUsage } from '@/features/usage/api';
import type { UsageRange } from '@/features/usage/schema';

export const usageKeys = {
  all: ['usage'] as const,
  range: (range: UsageRange) => [...usageKeys.all, range] as const,
};

/**
 * A minute of staleness matches the accounting nature of the source: these are
 * usage_records aggregates, not the live operational metrics Grafana shows, so
 * there is no reason to poll harder than the dashboard totals do.
 */
export function useUsage(range: UsageRange) {
  return useQuery({
    queryKey: usageKeys.range(range),
    queryFn: () => getUsage(range),
    staleTime: 60_000,
  });
}
