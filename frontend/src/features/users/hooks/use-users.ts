'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  createUser,
  deleteUser,
  issueInvitation,
  issuePasswordReset,
  listUsers,
  updateUser,
} from '@/features/users/api';
import type {
  CreateUserInput,
  UpdateUserInput,
} from '@/features/users/schema';
import { describeError } from '@/components/composed/error-state';

export const userKeys = {
  all: ['users'] as const,
  list: () => [...userKeys.all, 'list'] as const,
};

/**
 * `enabled` exists because listing users needs `user:read`, which only an
 * administrator holds. The API key dialog offers an owner picker to
 * administrators and must not fire this for a member, whose own dialog works
 * perfectly well without it and would collect a 403 for nothing.
 */
export function useUsers({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: userKeys.list(), queryFn: listUsers, enabled });
}

function useInvalidateUsers() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: userKeys.all });
}

export function useCreateUser() {
  const invalidate = useInvalidateUsers();
  return useMutation({
    mutationFn: (input: CreateUserInput) => createUser(input),
    onSuccess: async () => {
      await invalidate();
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useUpdateUser(id: string) {
  const invalidate = useInvalidateUsers();
  return useMutation({
    mutationFn: (input: UpdateUserInput) => updateUser(id, input),
    onSuccess: async () => {
      await invalidate();
      toast.success('User updated.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useDeleteUser() {
  const invalidate = useInvalidateUsers();
  return useMutation({
    mutationFn: (id: string) => deleteUser(id),
    onSuccess: async () => {
      await invalidate();
      toast.success('User removed.');
    },
  });
}

export function useIssueInvitation() {
  return useMutation({
    mutationFn: (userId: string) => issueInvitation(userId),
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useIssuePasswordReset() {
  return useMutation({
    mutationFn: (userId: string) => issuePasswordReset(userId),
    onError: (error) => toast.error(describeError(error)),
  });
}
