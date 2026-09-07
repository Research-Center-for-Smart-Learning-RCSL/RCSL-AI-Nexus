'use client';

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  createModel,
  deleteModel,
  getModel,
  listModels,
  listNodes,
  loadModel,
  readModelReference,
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
  reference: (ref: string) => [...modelKeys.all, 'reference', ref] as const,
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
export function useInvalidateModels() {
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

/**
 * What the host's weights declare for a reference, for the register form.
 *
 * **Debounced, because the input is a text field somebody types a reference
 * into.** The first version gated only on `length > 2`, which stops the first
 * two keystrokes and none of the rest: `gemma4:31b-it-q8_0` issued about
 * fifteen requests, each costing the server a manifest read and a GGUF header
 * scan, and each inserting a miss into the counter's cache of declared
 * lengths. Half a second after the typing stops is late enough that a
 * half-written reference is rarely asked about and early enough that the
 * suggestion is there before the operator reaches the field.
 *
 * `staleTime: Infinity` because the answer is a property of a file on disk: it
 * cannot change while the dialog is open without somebody pulling different
 * weights under the same name.
 *
 * A failure is silence rather than an error surface. The field it advises is
 * still typeable, and a register form that shows an error because a *hint*
 * could not be fetched would be worse than one that simply has no hint — but
 * the caller has to be able to tell "failed" from "there are no weights", so
 * the query state travels rather than just its data.
 */
export function useModelReference(ref: string) {
  const settled = useDebounced(ref.trim(), 500);
  return useQuery({
    queryKey: modelKeys.reference(settled),
    queryFn: () => readModelReference(settled),
    enabled: settled.length > 2,
    staleTime: Infinity,
    retry: false,
  });
}

/** The value once it has stopped changing for `delay` milliseconds. */
function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return settled;
}
