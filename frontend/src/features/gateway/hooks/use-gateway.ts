'use client';

import { useQuery } from '@tanstack/react-query';

import { readGatewayInfo } from '@/features/gateway/api';

export const gatewayKeys = {
  all: ['gateway'] as const,
  info: () => [...gatewayKeys.all, 'info'] as const,
};

/**
 * The base URL comes from configuration and the capability set from the
 * routing policies, so this changes about as often as a deployment does.
 * Cached accordingly: it is read on the API keys page, in the issue dialog and
 * on the documentation page, and refetching it three times tells nobody
 * anything new.
 */
export function useGatewayInfo() {
  return useQuery({
    queryKey: gatewayKeys.info(),
    queryFn: readGatewayInfo,
    staleTime: 5 * 60_000,
  });
}
