'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { getOwnUsage, getUsage, listUsageRecords } from '@/features/usage/api';
import type { UsageRange, UsageRecordFilters } from '@/features/usage/schema';

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
  records: (filters: UsageRecordFilters) => [...usageKeys.all, 'records', filters] as const,
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

/**
 * Server-paged, like the refusals table and the audit log, and for the same
 * reason: append-only, and anyone holding a key can add to it.
 *
 * Ten seconds rather than the minute the charts use. Somebody opens this
 * because of a request that just happened — an integrator quoting a time, a
 * key that was just given a new setting — and a minute-old page is one that may
 * not contain it yet.
 */
export function useUsageRecords(filters: UsageRecordFilters) {
  return useQuery({
    queryKey: usageKeys.records(filters),
    queryFn: () => listUsageRecords(filters),
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });
}
