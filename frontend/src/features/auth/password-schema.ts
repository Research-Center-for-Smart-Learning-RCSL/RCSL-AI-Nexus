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

/**
 * Past this the backend length-checks and accepts without scoring, because
 * zxcvbn's matching is superlinear in length. Mirrored here so a passphrase
 * long enough to skip the estimator on the API cannot be refused by the form.
 */
export const PASSWORD_MAX_SCORED_LENGTH = 128;

const SEPARATORS = /[@._\-+\s]+/;
const MIN_USER_INPUT_LENGTH = 3;

/**
 * The account's own login and display name, in the forms zxcvbn can match.
 *
 * **This mirrors `_expand` in `backend/app/adapters/crypto/zxcvbn_policy.py`
 * and has to keep mirroring it.** zxcvbn matches `user_inputs` as whole
 * dictionary entries, so offering only `jocelyn.tanaka@example.org` does not
 * catch `jocelyn.tanaka2026` — the password contains the memorable part of the
 * address, not the address. The local part is kept whole, punctuation
 * included: split into `jocelyn` and `tanaka` alone, the dot between them is
 * unmatched and zxcvbn charges a brute-force segment for it, which carries
 * that password from a score of 1 back to 4.
 *
 * Until 2026-08-18 this file passed no user inputs at all, so the browser
 * scored a password the API would score differently, and the form could accept
 * what the API then refused — the one direction `frontend.md` section 3 says
 * must never happen.
 */
export function expandUserInputs(values: readonly string[]): string[] {
  const expanded: string[] = [];
  for (const value of values) {
    const candidate = value.trim().toLowerCase();
    if (!candidate) continue;

    expanded.push(candidate);
    if (candidate.includes('@')) {
      expanded.push(candidate.split('@', 1)[0]!);
    }
    expanded.push(...candidate.split(SEPARATORS));
    // Run together as well, since `jocelyntanaka` is as likely a choice.
    expanded.push(candidate.replace(new RegExp(SEPARATORS, 'g'), ''));
  }
  return [...new Set(expanded.filter((v) => v.length >= MIN_USER_INPUT_LENGTH))].sort();
}

function meetsThreshold(password: string, userInputs: readonly string[]): boolean {
  if (password.length > PASSWORD_MAX_SCORED_LENGTH) return true;
  return zxcvbn(password, expandUserInputs(userInputs)).score >= PASSWORD_MIN_SCORE;
}

/**
 * `userInputs` is what the screen knows about the account — a login, a display
 * name — and every screen that has one should pass it. Omitting it scores the
 * password more generously than the API will.
 */
export function makePasswordSchema(userInputs: readonly string[] = []) {
  return z
    .string()
    .min(PASSWORD_MIN_LENGTH, `At least ${PASSWORD_MIN_LENGTH} characters.`)
    .refine((value) => meetsThreshold(value, userInputs), {
      message: 'Too easy to guess. Longer, or less predictable.',
    });
}

export const passwordSchema = makePasswordSchema();

export type PasswordStrength = {
  score: 0 | 1 | 2 | 3 | 4;
  meetsThreshold: boolean;
  warning: string;
  suggestions: string[];
};

export function scorePassword(
  password: string,
  userInputs: readonly string[] = [],
): PasswordStrength {
  if (!password) {
    return { score: 0, meetsThreshold: false, warning: '', suggestions: [] };
  }
  if (password.length > PASSWORD_MAX_SCORED_LENGTH) {
    return { score: 4, meetsThreshold: true, warning: '', suggestions: [] };
  }
  const result = zxcvbn(password, expandUserInputs(userInputs));
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
export function makeAcceptInvitationSchema(userInputs: readonly string[] = []) {
  return z
    .object({
      password: makePasswordSchema(userInputs),
      password_confirmation: z.string(),
      totp_code: z.string().regex(/^\d{6}$/, 'Six digits.'),
    })
    .refine((values) => values.password === values.password_confirmation, PASSWORDS_MATCH);
}

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
export function makeResetPasswordSchema(userInputs: readonly string[] = []) {
  return z
    .object({
      password: makePasswordSchema(userInputs),
      password_confirmation: z.string(),
    })
    .refine((values) => values.password === values.password_confirmation, PASSWORDS_MATCH);
}

export const resetPasswordSchema = z
  .object({
    password: passwordSchema,
    password_confirmation: z.string(),
  })
  .refine((values) => values.password === values.password_confirmation, PASSWORDS_MATCH);
export type ResetPasswordInput = z.infer<typeof resetPasswordSchema>;

export function makeChangePasswordSchema(userInputs: readonly string[] = []) {
  return z
    .object({
      current_password: z.string().min(1, 'Required'),
      password: makePasswordSchema(userInputs),
      password_confirmation: z.string(),
    })
    .refine((values) => values.password === values.password_confirmation, PASSWORDS_MATCH);
}

export const changePasswordSchema = z
  .object({
    current_password: z.string().min(1, 'Required'),
    password: passwordSchema,
    password_confirmation: z.string(),
  })
  .refine((values) => values.password === values.password_confirmation, PASSWORDS_MATCH);
export type ChangePasswordInput = z.infer<typeof changePasswordSchema>;
