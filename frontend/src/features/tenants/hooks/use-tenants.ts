'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { createTenant, listTenants } from '@/features/tenants/api';
import type { CreateTenantInput } from '@/features/tenants/schema';

export const tenantKeys = {
  all: ['tenants'] as const,
  list: () => [...tenantKeys.all, 'list'] as const,
};

export function useTenants() {
  return useQuery({
    queryKey: tenantKeys.list(),
    queryFn: listTenants,
    // Tenants change rarely; no need to poll.
    staleTime: 5 * 60_000,
  });
}

export function useCreateTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateTenantInput) => createTenant(input),
    // The dialog surfaces the returned invitation link and the error itself,
    // so no toast here; it just refreshes the list.
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: tenantKeys.all });
    },
  });
}
