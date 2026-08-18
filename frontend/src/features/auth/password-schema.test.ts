import { describe, expect, it } from 'vitest';

import {
  PASSWORD_MAX_SCORED_LENGTH,
  PASSWORD_MIN_LENGTH,
  acceptInvitationSchema,
  changePasswordSchema,
  expandUserInputs,
  makePasswordSchema,
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


describe('scoring against the account itself', () => {
  const LOGIN = 'jocelyn.tanaka@example.org';

  it('accepts a password built out of the login when nothing is passed', () => {
    // Not an endorsement: this is what the form did until 2026-08-18, and it is
    // the reason the API could refuse something the browser had accepted.
    expect(passwordSchema.safeParse('jocelyn.tanaka2026').success).toBe(true);
  });

  it('refuses that same password once the login is passed', () => {
    expect(makePasswordSchema([LOGIN]).safeParse('jocelyn.tanaka2026').success).toBe(false);
  });

  it('refuses the display name run together, which is as likely a choice', () => {
    expect(makePasswordSchema(['Jocelyn Tanaka']).safeParse('jocelyntanaka!!').success).toBe(
      false,
    );
  });

  it('still accepts a password unrelated to the account', () => {
    expect(makePasswordSchema([LOGIN, 'Jocelyn Tanaka']).safeParse(STRONG).success).toBe(true);
  });

  it('scores the meter against the same inputs as the schema', () => {
    expect(scorePassword('jocelyn.tanaka2026', [LOGIN]).meetsThreshold).toBe(false);
    expect(scorePassword('jocelyn.tanaka2026').meetsThreshold).toBe(true);
  });
});

describe('expandUserInputs', () => {
  // Mirrors `_expand` in backend/app/adapters/crypto/zxcvbn_policy.py. If the
  // two ever disagree, the form and the API disagree about the same password.
  it('keeps the local part whole as well as splitting it', () => {
    // Verified against `_expand(['Jocelyn.Tanaka@example.org'])` in the Python
    // policy on 2026-08-18: the two return the same list, element for element.
    expect(expandUserInputs(['Jocelyn.Tanaka@example.org'])).toEqual([
      'example',
      'jocelyn',
      'jocelyn.tanaka',
      'jocelyn.tanaka@example.org',
      'jocelyntanakaexampleorg',
      'org',
      'tanaka',
    ]);
  });

  it('keeps a spaced name whole, split, and run together', () => {
    expect(expandUserInputs(['Jocelyn Tanaka'])).toEqual([
      'jocelyn',
      'jocelyn tanaka',
      'jocelyntanaka',
      'tanaka',
    ]);
  });

  it('drops fragments shorter than three characters, and empty inputs', () => {
    // `a` and `b` go; `a b cd` survives whole, and so does the run-together
    // form — the same two the Python side keeps.
    expect(expandUserInputs(['a b cd', '', '   '])).toEqual(['a b cd', 'abcd']);
  });
});

describe('the ceiling the backend stops scoring at', () => {
  it('accepts anything past it rather than refusing what the API would allow', () => {
    const long = 'a'.repeat(PASSWORD_MAX_SCORED_LENGTH + 1);
    expect(makePasswordSchema(['a']).safeParse(long).success).toBe(true);
    expect(scorePassword(long).meetsThreshold).toBe(true);
  });
});
