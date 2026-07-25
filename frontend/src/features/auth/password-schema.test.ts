import { describe, expect, it } from 'vitest';

import {
  PASSWORD_MIN_LENGTH,
  acceptInvitationSchema,
  changePasswordSchema,
  passwordSchema,
  scorePassword,
} from '@/features/auth/password-schema';

const STRONG = 'correct horse battery staple';

describe('passwordSchema', () => {
  it('rejects a password shorter than the minimum length', () => {
    expect(passwordSchema.safeParse('a'.repeat(PASSWORD_MIN_LENGTH - 1)).success).toBe(false);
  });

  it('rejects a long but trivially guessable password', () => {
    expect(passwordSchema.safeParse('a'.repeat(20)).success).toBe(false);
  });

  it('accepts a long, unpredictable password', () => {
    expect(passwordSchema.safeParse(STRONG).success).toBe(true);
  });
});

describe('scorePassword', () => {
  it('reports nothing for an empty input', () => {
    expect(scorePassword('')).toMatchObject({ score: 0, meetsThreshold: false });
  });

  it('requires both length and strength to meet the threshold', () => {
    // Strong entropy but too short: fails on length.
    expect(scorePassword('Tr0ub4dor&3').meetsThreshold).toBe(false);
    expect(scorePassword(STRONG).meetsThreshold).toBe(true);
  });
});

describe('acceptInvitationSchema', () => {
  const base = {
    password: STRONG,
    password_confirmation: STRONG,
    totp_code: '123456',
  };

  it('accepts a well-formed enrolment', () => {
    expect(acceptInvitationSchema.safeParse(base).success).toBe(true);
  });

  it('rejects a TOTP code that is not six digits', () => {
    expect(acceptInvitationSchema.safeParse({ ...base, totp_code: '12345' }).success).toBe(false);
    expect(acceptInvitationSchema.safeParse({ ...base, totp_code: 'abcdef' }).success).toBe(false);
  });

  it('flags a confirmation mismatch on the confirmation field', () => {
    const result = acceptInvitationSchema.safeParse({
      ...base,
      password_confirmation: `${STRONG}!`,
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.path).toEqual(['password_confirmation']);
    }
  });
});

describe('changePasswordSchema', () => {
  it('requires the current password to be present', () => {
    const result = changePasswordSchema.safeParse({
      current_password: '',
      password: STRONG,
      password_confirmation: STRONG,
    });
    expect(result.success).toBe(false);
  });
});
