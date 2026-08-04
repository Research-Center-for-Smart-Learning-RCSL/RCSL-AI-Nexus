'use client';

import { useQuery } from '@tanstack/react-query';

import { getHostStatus } from '@/features/host/api';

export const hostKeys = { all: ['host'] as const };

/**
 * Polled, unlike the accounting reads next to it.
 *
 * Free memory is the one figure on these screens that is only useful if it is
 * current: it is read to answer "can I load this model now". Fifteen seconds is
 * the interval — the agent's own cost is a `vm_stat` and a `statfs`, so the
 * limit is how often a person can act on the answer, not the machine.
 */
export function useHostStatus() {
  return useQuery({
    queryKey: hostKeys.all,
    queryFn: getHostStatus,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });
}
