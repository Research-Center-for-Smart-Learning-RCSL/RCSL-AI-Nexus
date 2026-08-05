'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  createPromptTemplate,
  deletePromptTemplate,
  listPromptTemplates,
  updatePromptTemplate,
} from '@/features/prompt-templates/api';
import type { PromptTemplateFormValues } from '@/features/prompt-templates/schema';
import { describeError } from '@/components/composed/error-state';

export const promptTemplateKeys = {
  all: ['prompt-templates'] as const,
  list: () => [...promptTemplateKeys.all, 'list'] as const,
};

/**
 * `prompt:read` is a base scope, so this is enabled for every signed-in
 * caller: choosing a template is part of asking a question, and the chat
 * panel's picker reads the same list this screen does.
 */
export function usePromptTemplates({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: promptTemplateKeys.list(),
    queryFn: listPromptTemplates,
    enabled,
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: promptTemplateKeys.all });
}

export function useCreatePromptTemplate() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (input: PromptTemplateFormValues) => createPromptTemplate(input),
    onSuccess: async () => {
      await invalidate();
      toast.success('Template created.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useUpdatePromptTemplate(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (input: Partial<PromptTemplateFormValues>) => updatePromptTemplate(id, input),
    onSuccess: async () => {
      await invalidate();
      toast.success('Template updated.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useDeletePromptTemplate() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => deletePromptTemplate(id),
    onSuccess: async () => {
      await invalidate();
      toast.success('Template deleted. Requests naming it are now refused.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}
