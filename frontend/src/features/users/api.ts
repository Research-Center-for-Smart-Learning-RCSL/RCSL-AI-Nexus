import { api } from '@/lib/api-client';
import {
  invitationSchema,
  roleCatalogueSchema,
  userListSchema,
  userSchema,
  type CreateUserInput,
  type Invitation,
  type RoleCatalogueEntry,
  type UpdateUserInput,
  type User,
} from '@/features/users/schema';

const BASE = '/users';

/**
 * What each role actually grants, from the table the backend enforces.
 *
 * Fetched rather than hardcoded so the screen explaining the roles cannot
 * describe a permission the platform does not grant. Readable by any
 * authenticated caller: it is a fixed table and says nothing about who holds
 * which role.
 */
export async function listRoles(): Promise<RoleCatalogueEntry[]> {
  return roleCatalogueSchema.parse(await api.get<unknown>('/roles'));
}

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

/**
 * Open (minutes > 0) or close (0) the account's debug window: while it is
 * open, error responses to this person carry the operator-facing detail that
 * is otherwise log-only. Time-boxed by the backend to at most 24 hours, and
 * audited, because it loosens an information control.
 *
 * The counterpart of the API-key window, and the half that covers this screen:
 * the management UI authenticates by session and carries no API key, so an
 * administrator debugging the admin UI itself has no key on which to open one.
 */
export async function setUserDebugWindow(
  userId: string,
  minutes: number,
): Promise<User> {
  return userSchema.parse(
    await api.post<unknown>(`${BASE}/${userId}/debug`, { minutes }),
  );
}

/** Administrator-issued password reset link. Same shape as an invitation. */
export async function issuePasswordReset(userId: string): Promise<Invitation> {
  return invitationSchema.parse(
    await api.post<unknown>(`${BASE}/${userId}/password-reset`),
  );
}
