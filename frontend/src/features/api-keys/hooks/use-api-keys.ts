'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  issueApiKey,
  listApiKeys,
  revokeApiKey,
  setDebugWindow,
  updateApiKey,
} from '@/features/api-keys/api';
import type {
  CreateApiKeyPayload,
  UpdateApiKeyPayload,
} from '@/features/api-keys/schema';
import { describeError } from '@/components/composed/error-state';

export const apiKeyKeys = {
  all: ['api-keys'] as const,
  list: () => [...apiKeyKeys.all, 'list'] as const,
};

export function useApiKeys() {
  return useQuery({ queryKey: apiKeyKeys.list(), queryFn: listApiKeys });
}

function useInvalidateApiKeys() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: apiKeyKeys.all });
}

export function useIssueApiKey() {
  const invalidate = useInvalidateApiKeys();
  return useMutation({
    mutationFn: (input: CreateApiKeyPayload) => issueApiKey(input),
    onSuccess: async () => {
      await invalidate();
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useUpdateApiKey(keyId: string) {
  const invalidate = useInvalidateApiKeys();
  return useMutation({
    mutationFn: (input: Partial<UpdateApiKeyPayload>) =>
      updateApiKey(keyId, input),
    onSuccess: async () => {
      await invalidate();
      toast.success('Key updated.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useRevokeApiKey() {
  const invalidate = useInvalidateApiKeys();
  return useMutation({
    mutationFn: (keyId: string) => revokeApiKey(keyId),
    onSuccess: async () => {
      await invalidate();
      toast.success('Key revoked. It stops working immediately.');
    },
  });
}

/**
 * Opens (minutes > 0) or closes (0) the key's debug window. While it is open,
 * error responses to this key carry operator-facing detail; the backend caps
 * it at 24 hours and audits the change.
 */
export function useSetDebugWindow() {
  const invalidate = useInvalidateApiKeys();
  return useMutation({
    mutationFn: ({ keyId, minutes }: { keyId: string; minutes: number }) =>
      setDebugWindow(keyId, minutes),
    onSuccess: async (_key, { minutes }) => {
      await invalidate();
      toast.success(
        minutes > 0
          ? `Debug window open for ${minutes} minutes. Error responses to this key now carry detail.`
          : 'Debug window closed.',
      );
    },
    onError: (error) => toast.error(describeError(error)),
  });
}
