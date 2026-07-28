import { describe, expect, it } from 'vitest';

import {
  canManageKey,
  cidrTextSchema,
  createApiKeySchema,
  parseCidrText,
  toDateInput,
  updateApiKeySchema,
  type ApiKey,
} from '@/features/api-keys/schema';

const KEY: ApiKey = {
  key_id: '0123456789abcdef',
  name: 'ci',
  scopes: ['chat'],
  rate_limit_rpm: 60,
  quota_tokens_per_day: 100_000,
  allowed_cidrs: [],
  expires_at: '2027-01-01T00:00:00Z',
  owner_id: 'u2',
  owner_display: 'Member',
  revoked_at: null,
  created_at: '2026-07-01T00:00:00Z',
  last_used_at: null,
};

function parseUpdate(overrides: Record<string, unknown> = {}) {
  return updateApiKeySchema.safeParse({
    name: 'ci',
    scopes: ['chat'],
    rate_limit_rpm: '60',
    quota_tokens_per_day: '100000',
    allowed_cidrs_text: '',
    expires_at: '2027-01-01',
    ...overrides,
  });
}

describe('parseCidrText', () => {
  it('splits on newlines, commas and stray whitespace', () => {
    expect(parseCidrText('10.0.0.0/8,\n 203.0.113.0/24 \n\n')).toEqual([
      '10.0.0.0/8',
      '203.0.113.0/24',
    ]);
  });

  it('yields an empty list for blank text, which means unrestricted', () => {
    expect(parseCidrText('   \n ')).toEqual([]);
  });
});

describe('cidrTextSchema', () => {
  it('accepts an empty field', () => {
    expect(cidrTextSchema.safeParse('').success).toBe(true);
  });

  it('accepts IPv4 and IPv6 ranges together', () => {
    expect(
      cidrTextSchema.safeParse('203.0.113.0/24\n2001:db8::/32').success,
    ).toBe(true);
  });

  it('rejects an entry with no prefix length', () => {
    expect(cidrTextSchema.safeParse('203.0.113.5').success).toBe(false);
  });

  it('rejects a bad entry among good ones', () => {
    // The rule must see the text the field holds. Validating a separately
    // built array is how the same rule can pass while never running.
    expect(
      cidrTextSchema.safeParse('10.0.0.0/8, 10.0.0.0/wide').success,
    ).toBe(false);
  });
});

function parseCreate(overrides: Record<string, unknown> = {}) {
  return createApiKeySchema.safeParse({
    name: 'ci',
    owner_id: 'u2',
    scopes: ['chat'],
    rate_limit_rpm: '60',
    quota_tokens_per_day: '1000000',
    allowed_cidrs_text: '',
    expires_at: '2027-01-01',
    ...overrides,
  });
}

describe('createApiKeySchema', () => {
  it('validates the CIDR field the form actually holds', () => {
    // The rule used to sit on an array the form never contained, while the
    // text was split into the request after validation had run.
    expect(parseCreate({ allowed_cidrs_text: '10.0.0.0/8' }).success).toBe(true);
    expect(parseCreate({ allowed_cidrs_text: '10.0.0.0' }).success).toBe(false);
  });

  it('requires an owner, which an administrator chooses', () => {
    expect(parseCreate({ owner_id: '' }).success).toBe(false);
  });

  it('refuses the unmetered values the backend also refuses', () => {
    expect(parseCreate({ rate_limit_rpm: '0' }).success).toBe(false);
    expect(parseCreate({ quota_tokens_per_day: '0' }).success).toBe(false);
  });
});

describe('updateApiKeySchema', () => {
  it('coerces the number inputs, which submit strings', () => {
    const result = parseUpdate();
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.rate_limit_rpm).toBe(60);
      expect(result.data.quota_tokens_per_day).toBe(100_000);
    }
  });

  it('refuses a zero rate limit, which the gateway reads as no limit', () => {
    expect(parseUpdate({ rate_limit_rpm: '0' }).success).toBe(false);
  });

  it('refuses a zero quota, which the update path stores literally', () => {
    expect(parseUpdate({ quota_tokens_per_day: '0' }).success).toBe(false);
  });

  it('requires at least one scope', () => {
    expect(parseUpdate({ scopes: [] }).success).toBe(false);
  });

  it('rejects an unknown capability', () => {
    expect(parseUpdate({ scopes: ['chatt'] }).success).toBe(false);
  });

  it('requires an expiry, because there is no "never"', () => {
    expect(parseUpdate({ expires_at: '' }).success).toBe(false);
  });

  it('rejects an unparsable CIDR through the field the form holds', () => {
    expect(parseUpdate({ allowed_cidrs_text: 'not-a-range' }).success).toBe(
      false,
    );
  });

  it('has no owner field, because an edit cannot move a key', () => {
    const result = parseUpdate();
    expect(result.success).toBe(true);
    if (result.success) expect('owner_id' in result.data).toBe(false);
  });
});

describe('toDateInput', () => {
  it('reduces a timestamp to what a date input accepts', () => {
    expect(toDateInput('2027-01-01T00:00:00Z')).toBe('2027-01-01');
  });

  it('returns empty for an unparsable value rather than a broken field', () => {
    expect(toDateInput('not a date')).toBe('');
  });
});

describe('canManageKey', () => {
  it('lets an owner manage their own key', () => {
    expect(canManageKey(KEY, { id: 'u2', isAdmin: false })).toBe(true);
  });

  it('refuses a member somebody else’s key', () => {
    expect(canManageKey(KEY, { id: 'someone-else', isAdmin: false })).toBe(
      false,
    );
  });

  it('lets an administrator manage any key', () => {
    expect(canManageKey(KEY, { id: 'admin-1', isAdmin: true })).toBe(true);
  });

  it('refuses everything when the viewer is unknown', () => {
    // `me` is null while the session loads and after a 401. Comparing against
    // it would otherwise make an unidentified viewer an owner of nothing in
    // particular.
    expect(canManageKey(KEY, { id: null, isAdmin: false })).toBe(false);
  });
});
