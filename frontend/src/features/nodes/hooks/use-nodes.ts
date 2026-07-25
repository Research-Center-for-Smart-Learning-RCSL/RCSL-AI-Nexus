'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  checkNodeHealth,
  createNode,
  deleteNode,
  listNodes,
  updateNode,
} from '@/features/nodes/api';
import type { CreateNodeInput, UpdateNodeInput } from '@/features/nodes/schema';
import { describeError } from '@/components/composed/error-state';

export const nodeKeys = {
  all: ['nodes'] as const,
  list: () => [...nodeKeys.all, 'list'] as const,
};

/**
 * Polled, because a node's status is observed by the backend heartbeat rather
 * than pushed. The interval is longer than the model list's: hardware state
 * moves on the order of the heartbeat, not the second.
 *
 * `features/models` keeps its own lightly-cached `useNodes` for the model form's
 * dropdown under the `['nodes']` key. This table's key sits under it, so the
 * invalidation below (keyed on the `['nodes']` prefix) refreshes both: a node
 * registered here shows up in that dropdown without a manual reload.
 */
export function useNodes() {
  return useQuery({
    queryKey: nodeKeys.list(),
    queryFn: listNodes,
    refetchInterval: 30_000,
  });
}

function useInvalidateNodes() {
  const queryClient = useQueryClient();
  // Also clears the `['nodes']` key the model form reads, since they share it.
  return () => queryClient.invalidateQueries({ queryKey: nodeKeys.all });
}

export function useCreateNode() {
  const invalidate = useInvalidateNodes();
  return useMutation({
    mutationFn: (input: CreateNodeInput) => createNode(input),
    onSuccess: async (node) => {
      await invalidate();
      toast.success(`Registered ${node.name}.`);
    },
    // A refused address is the SSRF guard rejecting a non-tailnet value, so the
    // server's message is shown verbatim rather than reworded.
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useUpdateNode(id: string) {
  const invalidate = useInvalidateNodes();
  return useMutation({
    mutationFn: (input: UpdateNodeInput) => updateNode(id, input),
    onSuccess: async () => {
      await invalidate();
      toast.success('Node updated.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useDeleteNode() {
  const invalidate = useInvalidateNodes();
  return useMutation({
    mutationFn: (id: string) => deleteNode(id),
    onSuccess: async () => {
      await invalidate();
      toast.success('Node removed.');
    },
    // Refused while models are still attached, with the server naming them.
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useCheckNodeHealth() {
  const invalidate = useInvalidateNodes();
  return useMutation({
    mutationFn: (id: string) => checkNodeHealth(id),
    onSuccess: async (node) => {
      await invalidate();
      toast.success(`${node.name} is ${node.status}.`);
    },
    onError: (error) => toast.error(describeError(error)),
  });
}
