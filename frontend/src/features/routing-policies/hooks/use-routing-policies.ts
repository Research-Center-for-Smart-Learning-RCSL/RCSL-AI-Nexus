'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { describeError } from '@/components/composed/error-state';
import {
  deleteRoutingPolicy,
  listRoutingPolicies,
  saveRoutingPolicy,
} from '@/features/routing-policies/api';
import type { SavePolicyRequest } from '@/features/routing-policies/schema';

export const routingPolicyKeys = {
  all: ['routing-policies'] as const,
  list: () => [...routingPolicyKeys.all, 'list'] as const,
};

export function useRoutingPolicies() {
  return useQuery({
    queryKey: routingPolicyKeys.list(),
    queryFn: listRoutingPolicies,
  });
}

/**
 * Every mutation invalidates rather than patching the cache, so the UI
 * resynchronises from the server instead of keeping a second copy of the truth
 * (frontend.md section 5).
 */
function useInvalidatePolicies() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: routingPolicyKeys.all });
}

export function useSaveRoutingPolicy() {
  const invalidate = useInvalidatePolicies();
  return useMutation({
    mutationFn: ({ capability, body }: { capability: string; body: SavePolicyRequest }) =>
      saveRoutingPolicy(capability, body),
    onSuccess: async (policy) => {
      await invalidate();
      toast.success(`Saved the ${policy.capability} policy.`);
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useDeleteRoutingPolicy() {
  const invalidate = useInvalidatePolicies();
  return useMutation({
    mutationFn: (capability: string) => deleteRoutingPolicy(capability),
    onSuccess: async () => {
      await invalidate();
      toast.success('Policy removed.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}
