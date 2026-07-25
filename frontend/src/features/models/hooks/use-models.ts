'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  createModel,
  deleteModel,
  getModel,
  listModels,
  listNodes,
  loadModel,
  startDownload,
  unloadModel,
  updateModel,
} from '@/features/models/api';
import type {
  CreateModelInput,
  UpdateModelInput,
} from '@/features/models/schema';
import { describeError } from '@/components/composed/error-state';

export const modelKeys = {
  all: ['models'] as const,
  list: () => [...modelKeys.all, 'list'] as const,
  detail: (id: string) => [...modelKeys.all, 'detail', id] as const,
};

export function useModels() {
  return useQuery({
    queryKey: modelKeys.list(),
    queryFn: listModels,
    // Load and unload are asynchronous on the backend, so the table refreshes
    // on a timer rather than pretending a mutation response is the final state.
    refetchInterval: 15_000,
  });
}

/**
 * Nodes change when hardware does, which is roughly never, so this is cached
 * for the session rather than polled beside the model list.
 */
export function useNodes() {
  return useQuery({
    queryKey: ['nodes'],
    queryFn: listNodes,
    staleTime: 5 * 60_000,
  });
}

export function useModel(id: string | null) {
  return useQuery({
    queryKey: modelKeys.detail(id ?? ''),
    queryFn: () => getModel(id as string),
    enabled: Boolean(id),
  });
}

/**
 * Every mutation invalidates rather than patching the cache, so the UI
 * resynchronises from the server instead of keeping a second copy of the truth
 * (frontend.md section 5).
 */
function useInvalidateModels() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: modelKeys.all });
}

export function useCreateModel() {
  const invalidate = useInvalidateModels();
  return useMutation({
    mutationFn: (input: CreateModelInput) => createModel(input),
    onSuccess: async (model) => {
      await invalidate();
      toast.success(`Registered ${model.alias}.`);
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useUpdateModel(id: string) {
  const invalidate = useInvalidateModels();
  return useMutation({
    mutationFn: (input: UpdateModelInput) => updateModel(id, input),
    onSuccess: async () => {
      await invalidate();
      toast.success('Model updated.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useDeleteModel() {
  const invalidate = useInvalidateModels();
  return useMutation({
    mutationFn: (id: string) => deleteModel(id),
    onSuccess: async () => {
      await invalidate();
      toast.success('Model removed from the registry.');
    },
  });
}

export function useLoadModel() {
  const invalidate = useInvalidateModels();
  return useMutation({
    mutationFn: (id: string) => loadModel(id),
    onSuccess: async () => {
      await invalidate();
      toast.success('Load requested.');
    },
    // A refusal here is usually the memory budget check asking for an unload
    // first, so the server's message is shown verbatim.
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useUnloadModel() {
  const invalidate = useInvalidateModels();
  return useMutation({
    mutationFn: (id: string) => unloadModel(id),
    onSuccess: async () => {
      await invalidate();
      toast.success('Unload requested.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useStartDownload() {
  const invalidate = useInvalidateModels();
  return useMutation({
    mutationFn: (id: string) => startDownload(id),
    onSuccess: async () => {
      await invalidate();
    },
    onError: (error) => toast.error(describeError(error)),
  });
}
