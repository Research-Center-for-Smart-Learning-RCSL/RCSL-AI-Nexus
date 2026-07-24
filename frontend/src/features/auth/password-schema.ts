import { z } from 'zod';
import zxcvbn from 'zxcvbn';

/**
 * Everything that depends on zxcvbn lives here, apart from the rest of the
 * auth schemas.
 *
 * The separation is a bundle-size decision, not a stylistic one. zxcvbn ships
 * a frequency dictionary of roughly 800 kB, and a single top-level import
 * pulls all of it into every route that touches the module. When these
 * declarations sat next to the login schemas, the sign-in page carried the
 * whole dictionary to validate a field it never scores. Only the screens that
 * actually set a password import this file.
 *
 * Rules mirror security.md section 5.3: minimum length 12, strength checked
 * with zxcvbn, and deliberately no composition rules. The threshold must match
 * what the backend enforces so the UI never accepts something the API will
 * reject (frontend.md section 3).
 */

export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MIN_SCORE = 3; // zxcvbn 0-4; 3 is "safely unguessable".

export const passwordSchema = z
  .string()
  .min(PASSWORD_MIN_LENGTH, `At least ${PASSWORD_MIN_LENGTH} characters.`)
  .refine((value) => zxcvbn(value).score >= PASSWORD_MIN_SCORE, {
    message: 'Too easy to guess. Longer, or less predictable.',
  });

export type PasswordStrength = {
  score: 0 | 1 | 2 | 3 | 4;
  meetsThreshold: boolean;
  warning: string;
  suggestions: string[];
};

export function scorePassword(password: string): PasswordStrength {
  if (!password) {
    return { score: 0, meetsThreshold: false, warning: '', suggestions: [] };
  }
  const result = zxcvbn(password);
  return {
    score: result.score as PasswordStrength['score'],
    meetsThreshold:
      result.score >= PASSWORD_MIN_SCORE && password.length >= PASSWORD_MIN_LENGTH,
    warning: result.feedback.warning ?? '',
    suggestions: result.feedback.suggestions ?? [],
  };
}

// Not `as const`: zod expects a mutable PropertyKey[] for `path`.
const PASSWORDS_MATCH = {
  message: 'The two passwords do not match.',
  path: ['password_confirmation'] as PropertyKey[],
};

/** Invitation acceptance: password and TOTP enrolment in one flow. */
export const acceptInvitationSchema = z
  .object({
    password: passwordSchema,
    password_confirmation: z.string(),
    // Proves the authenticator was actually configured, so an account never
    // exists in a password-only state (security.md section 5.3).
    totp_code: z.string().regex(/^\d{6}$/, 'Six digits.'),
  })
  .refine((values) => values.password === values.password_confirmation, PASSWORDS_MATCH);
export type AcceptInvitationInput = z.infer<typeof acceptInvitationSchema>;

/** Password reset: same shape minus TOTP enrolment (frontend.md section 3). */
export const resetPasswordSchema = z
  .object({
    password: passwordSchema,
    password_confirmation: z.string(),
  })
  .refine((values) => values.password === values.password_confirmation, PASSWORDS_MATCH);
export type ResetPasswordInput = z.infer<typeof resetPasswordSchema>;

export const changePasswordSchema = z
  .object({
    current_password: z.string().min(1, 'Required'),
    password: passwordSchema,
    password_confirmation: z.string(),
  })
  .refine((values) => values.password === values.password_confirmation, PASSWORDS_MATCH);
export type ChangePasswordInput = z.infer<typeof changePasswordSchema>;
