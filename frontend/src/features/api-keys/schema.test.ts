import { describe, expect, it } from 'vitest';

import {
  canManageKey,
  cidrTextSchema,
  createApiKeySchema,
  defaultCapabilityField,
  defaultCapabilityPayload,
  NO_DEFAULT,
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

describe('the default capability', () => {
  it('parses to "refuse" when the form never mentions it', () => {
    const result = parseUpdate();
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.default_capability).toBe(NO_DEFAULT);
    }
  });

  it('accepts a capability the key is being issued for', () => {
    expect(
      parseCreate({ scopes: ['chat', 'code'], default_capability: 'code' })
        .success,
    ).toBe(true);
  });

  it('refuses one outside the capabilities in the same form', () => {
    // The server refuses this too, with a 409 on a request that also carried
    // the capability edit. Catching it here is what puts the message on the
    // field rather than leaving the operator to guess which half was wrong.
    const result = parseCreate({
      scopes: ['chat'],
      default_capability: 'code',
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path).toEqual(['default_capability']);
    }
  });

  it('refuses it on an edit that narrows the capabilities out from under it', () => {
    expect(
      parseUpdate({ scopes: ['chat'], default_capability: 'code' }).success,
    ).toBe(false);
  });

  it('carries null on the wire and a word in the control', () => {
    // `''` would be indistinguishable from "nothing chosen" in a select, which
    // is the one value the ordinary setting must not render as.
    expect(defaultCapabilityPayload(NO_DEFAULT)).toBeNull();
    expect(defaultCapabilityPayload('code')).toBe('code');
    expect(defaultCapabilityField(null)).toBe(NO_DEFAULT);
    expect(defaultCapabilityField('code')).toBe('code');
  });
});

describe('toDateInput', () => {
  it('reduces a timestamp to what a date input accepts', () => {
    expect(toDateInput('2027-01-01T00:00:00Z')).toBe('2027-01-01');
  });

  it('loses the time of day, which is why an unchanged expiry is not resent', () => {
    // Round-tripping this value back would move the expiry to midnight, so the
    // edit dialog sends the field only when it was actually changed.
    expect(toDateInput('2027-01-01T18:30:00Z')).toBe('2027-01-01');
  });

  it('returns empty for an unparsable value rather than a broken field', () => {
    expect(toDateInput('not a date')).toBe('');
  });
});

describe('canManageKey', () => {
  it('lets an owner manage their own key', () => {
    expect(
      canManageKey(KEY, { id: 'u2', mayWriteAny: false, mayWriteOwn: true }),
    ).toBe(true);
  });

  it('refuses a member somebody else’s key', () => {
    expect(
      canManageKey(KEY, {
        id: 'someone-else',
        mayWriteAny: false,
        mayWriteOwn: true,
      }),
    ).toBe(false);
  });

  it('lets anyone holding api_key:write_any manage any key', () => {
    // The scope, not the role. `tenant_admin` holds it inside its own tenant
    // and `operator` deliberately does not hold it at all, so asking "is an
    // administrator" would have been right about one of the three.
    expect(
      canManageKey(KEY, {
        id: 'admin-1',
        mayWriteAny: true,
        mayWriteOwn: false,
      }),
    ).toBe(true);
  });

  it('refuses an auditor even their own key', () => {
    // Owning the row stopped being enough when a role arrived that holds no
    // write at all. `auditor` drops `api_key:write_own`, so its keys are
    // listed and Rotate and Revoke are not offered — the role exists so that
    // its holder leaves only a read behind.
    expect(
      canManageKey(KEY, { id: 'u2', mayWriteAny: false, mayWriteOwn: false }),
    ).toBe(false);
  });

  it('refuses everything when the viewer is unknown', () => {
    // `me` is null while the session loads and after a 401. Comparing against
    // it would otherwise make an unidentified viewer an owner of nothing in
    // particular.
    expect(
      canManageKey(KEY, { id: null, mayWriteAny: false, mayWriteOwn: true }),
    ).toBe(false);
  });
});
