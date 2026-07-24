import { api } from '@/lib/api-client';
import {
  acceptInvitationResultSchema,
  enrolmentSchema,
  loginChallengeSchema,
  type AcceptInvitationResult,
  type Enrolment,
  type LoginChallenge,
} from '@/features/auth/schema';
// Type-only import, so this does not pull zxcvbn into anything importing api.ts.
import type { ChangePasswordInput } from '@/features/auth/password-schema';

const BASE = '/auth';

/**
 * Step one of two. A successful response is a challenge, never a session:
 * password verification and TOTP verification are separate steps and both are
 * rate limited (security.md section 5.3).
 */
export async function loginWithPassword(input: {
  login: string;
  password: string;
}): Promise<LoginChallenge> {
  return loginChallengeSchema.parse(
    await api.post<unknown>(`${BASE}/login`, input),
  );
}

/** Step two. Issues the session cookie; nothing is returned to the client. */
export async function loginWithTotp(input: {
  challenge: string;
  code: string;
}): Promise<void> {
  await api.post<void>(`${BASE}/login/totp`, input);
}

/** Second-step alternative when the authenticator is lost. Single use. */
export async function loginWithRecoveryCode(input: {
  challenge: string;
  recovery_code: string;
}): Promise<void> {
  await api.post<void>(`${BASE}/login/recovery-code`, input);
}

export async function logout(): Promise<void> {
  await api.post<void>(`${BASE}/logout`);
}

/**
 * Validates the single-use token and returns the TOTP provisioning material.
 * Called before the form renders, so an expired or consumed link fails fast
 * rather than after the user has chosen a password.
 */
export async function getInvitation(token: string): Promise<Enrolment> {
  return enrolmentSchema.parse(
    await api.get<unknown>('/invitations', { query: { token } }),
  );
}

/**
 * Consumes the invitation. The recovery codes in the response are the only
 * copy that will ever exist.
 */
export async function acceptInvitation(input: {
  token: string;
  password: string;
  totp_code: string;
}): Promise<AcceptInvitationResult> {
  return acceptInvitationResultSchema.parse(
    await api.post<unknown>('/invitations/accept', input),
  );
}

/** Administrator-issued reset link. No TOTP enrolment: it already exists. */
export async function verifyResetToken(token: string): Promise<{ login: string }> {
  return api.get<{ login: string }>('/password-resets', { query: { token } });
}

export async function resetPassword(input: {
  token: string;
  password: string;
}): Promise<void> {
  await api.post<void>('/password-resets/consume', input);
}

/** Changing a password invalidates every other session for that user. */
export async function changePassword(
  input: ChangePasswordInput,
): Promise<void> {
  await api.post<void>('/me/password', {
    current_password: input.current_password,
    password: input.password,
  });
}

/** Re-enrol TOTP from account settings. Returns fresh provisioning material. */
export async function beginTotpReenrolment(): Promise<Enrolment> {
  return enrolmentSchema.parse(await api.post<unknown>('/me/totp'));
}

export async function confirmTotpReenrolment(input: {
  code: string;
}): Promise<AcceptInvitationResult> {
  return acceptInvitationResultSchema.parse(
    await api.post<unknown>('/me/totp/confirm', input),
  );
}
