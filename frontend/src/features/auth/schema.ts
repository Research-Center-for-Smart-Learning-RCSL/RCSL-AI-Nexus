import { z } from 'zod';

/**
 * Auth schemas that do not touch zxcvbn.
 *
 * Anything requiring password strength scoring lives in `password-schema.ts`
 * instead. That module pulls in a roughly 800 kB frequency dictionary, and
 * keeping it out of this file is what stops the sign-in page from shipping it
 * to validate a field it never scores.
 */

export const loginStepOneSchema = z.object({
  login: z.string().min(1, 'Required'),
  password: z.string().min(1, 'Required'),
});
export type LoginStepOneInput = z.infer<typeof loginStepOneSchema>;

/**
 * What the second-step *form* holds, which is the code and nothing else.
 *
 * `challenge` used to be required here and is not a field: it is held in
 * `useLogin` state and attached by `submitTotp` on its way to the API. The
 * resolver therefore failed on every submission, `handleSubmit` never called
 * the hook, and the error was attached to a name no `FormField` renders — so
 * entering a correct code produced no request, no error and no visible change.
 * A form schema describes the form; the request shape is `api.ts`'s business.
 */
export const loginStepTwoSchema = z.object({
  code: z.string().regex(/^\d{6}$/, 'Six digits.'),
});
export type LoginStepTwoInput = z.infer<typeof loginStepTwoSchema>;

export const recoveryCodeLoginSchema = z.object({
  recovery_code: z.string().min(1, 'Required'),
});
export type RecoveryCodeLoginInput = z.infer<typeof recoveryCodeLoginSchema>;

/** What the invitation acceptance screen needs before it can render the QR. */
export const enrolmentSchema = z.object({
  /** `otpauth://` URI. Rendered as a QR code and offered as text. */
  provisioning_uri: z.string(),
  /** Base32 secret, for manual entry when a camera is unavailable. */
  secret: z.string(),
  login: z.string(),
});
export type Enrolment = z.infer<typeof enrolmentSchema>;

export const acceptInvitationResultSchema = z.object({
  /** Ten single-use codes, shown exactly once. */
  recovery_codes: z.array(z.string()).min(1),
});
export type AcceptInvitationResult = z.infer<typeof acceptInvitationResultSchema>;

export const loginChallengeSchema = z.object({
  /** Opaque handle for the second step; not a session. */
  challenge: z.string(),
  /** Only ever 'totp' in Phase 1, kept open for recovery-code entry. */
  next: z.enum(['totp']),
});
export type LoginChallenge = z.infer<typeof loginChallengeSchema>;
