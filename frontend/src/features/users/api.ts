import { api } from '@/lib/api-client';
import {
  invitationSchema,
  userListSchema,
  userSchema,
  type CreateUserInput,
  type Invitation,
  type UpdateUserInput,
  type User,
} from '@/features/users/schema';

const BASE = '/users';

export async function listUsers(): Promise<User[]> {
  return userListSchema.parse(await api.get<unknown>(BASE));
}

/**
 * Creates the account and issues the first invitation in one call. The returned
 * invitation carries the single-use URL, which the caller must show once.
 */
export async function createUser(
  input: CreateUserInput,
): Promise<{ user: User; invitation: Invitation }> {
  const raw = await api.post<{ user: unknown; invitation: unknown }>(BASE, input);
  return {
    user: userSchema.parse(raw.user),
    invitation: invitationSchema.parse(raw.invitation),
  };
}

export async function updateUser(
  id: string,
  input: UpdateUserInput,
): Promise<User> {
  return userSchema.parse(await api.patch<unknown>(`${BASE}/${id}`, input));
}

export async function deleteUser(id: string): Promise<void> {
  await api.delete<void>(`${BASE}/${id}`);
}

/** Re-issues an invitation, for example after the 72 hour expiry. */
export async function issueInvitation(userId: string): Promise<Invitation> {
  return invitationSchema.parse(
    await api.post<unknown>(`${BASE}/${userId}/invitations`),
  );
}

/** Administrator-issued password reset link. Same shape as an invitation. */
export async function issuePasswordReset(userId: string): Promise<Invitation> {
  return invitationSchema.parse(
    await api.post<unknown>(`${BASE}/${userId}/password-reset`),
  );
}
