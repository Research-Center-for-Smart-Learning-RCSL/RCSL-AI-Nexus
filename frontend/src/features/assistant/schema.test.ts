import { describe, expect, it } from 'vitest';

import {
  proposalToFormPatch,
  readProposalFrame,
  type ProposalFields,
} from '@/features/assistant/schema';
import {
  applyProposalPatch,
  draftFor,
} from '@/features/api-keys/assistant-bridge';
import { NO_DEFAULT } from '@/features/api-keys/schema';

/**
 * The last gate before a language model's output lands in a form the operator
 * is one click from saving.
 *
 * The backend validates the same values against the same bounds, and that is
 * the check that counts — nothing here is a substitute for it. What these pin
 * is the second half of the promise: that a frame arriving on this connection
 * cannot put anything into the form that did not come through the schema, and
 * that applying a proposal changes only the fields it actually named.
 */

const validProposal = {
  action: 'create',
  fields: { scopes: ['chat'], rate_limit_rpm: 60 },
  rationale: 'A narrow key.',
};

describe('readProposalFrame', () => {
  it('accepts a well-formed proposal frame', () => {
    const found = readProposalFrame({ proposal: validProposal });

    expect(found?.action).toBe('create');
    expect(found?.fields.scopes).toEqual(['chat']);
  });

  it('returns null for every ordinary content frame', () => {
    // The reader offers each unrecognised frame without knowing what it is, so
    // this has to be quiet about the ones that are not proposals.
    expect(readProposalFrame({ choices: [{ delta: { content: 'hi' } }] })).toBeNull();
    expect(readProposalFrame({})).toBeNull();
    expect(readProposalFrame(null)).toBeNull();
    expect(readProposalFrame('proposal')).toBeNull();
  });

  it('rejects a field the platform does not accept', () => {
    // `strict()` on the fields object. An unexpected key means this is not the
    // frame it claims to be, and zod's default is to strip rather than refuse —
    // which would let `owner_id` through as a silently discarded key while the
    // rest of the proposal applied.
    expect(
      readProposalFrame({
        proposal: { ...validProposal, fields: { owner_id: 'someone-else' } },
      }),
    ).toBeNull();
  });

  it('rejects a rate limit of zero', () => {
    // Zero used to be a way to issue an unmetered key through a form that reads
    // as if it were tightening one. It is inexpressible on both sides now.
    expect(
      readProposalFrame({
        proposal: { ...validProposal, fields: { rate_limit_rpm: 0 } },
      }),
    ).toBeNull();
  });

  it('rejects a capability that cannot be issued', () => {
    // `assist` is routable, so a model that has seen the routing table could
    // name it. A key issued for it would reach the management assistant.
    expect(
      readProposalFrame({
        proposal: { ...validProposal, fields: { scopes: ['assist'] } },
      }),
    ).toBeNull();
  });

  it('rejects a proposal with no fields object at all', () => {
    expect(readProposalFrame({ proposal: { action: 'create' } })).toBeNull();
  });
});

describe('proposalToFormPatch', () => {
  it('names only the fields the proposal filled', () => {
    // An omitted field must leave what the operator typed alone. Filling it
    // with a default would turn "here is a better expiry" into "and I also
    // reset your rate limit", which is what would make the card untrustworthy.
    const patch = proposalToFormPatch({ rate_limit_rpm: 30 } as ProposalFields);

    expect(Object.keys(patch)).toEqual(['rate_limit_rpm']);
    expect(patch.rate_limit_rpm).toBe('30');
  });

  it('flattens the CIDR list into the textarea both dialogs use', () => {
    const patch = proposalToFormPatch({
      allowed_cidrs: ['203.0.113.0/24', '198.51.100.7/32'],
    } as ProposalFields);

    expect(patch.allowed_cidrs_text).toBe('203.0.113.0/24\n198.51.100.7/32');
  });

  it('narrows a timestamp to the date the input accepts', () => {
    const patch = proposalToFormPatch({
      expires_at: '2026-10-27T00:00:00Z',
    } as ProposalFields);

    expect(patch.expires_at).toBe('2026-10-27');
  });

  it('drops an unparsable date rather than blanking the field', () => {
    // Writing an empty string would clear a valid expiry and then fail the
    // field's own required rule, which reads as the form breaking itself.
    const patch = proposalToFormPatch({ expires_at: 'next Tuesday' } as ProposalFields);

    expect('expires_at' in patch).toBe(false);
  });
});

describe('applyProposalPatch', () => {
  it('writes only the fields a key form actually has', () => {
    const written: string[] = [];
    applyProposalPatch({ name: 'ci', owner_id: 'someone-else' }, (field) =>
      written.push(field),
    );

    // The allowlist, one layer below the schema that already refused it. Two
    // independent reasons `owner_id` cannot travel, which is deliberate: who
    // holds a key is an identity decision belonging to the owner picker.
    expect(written).toEqual(['name']);
  });

  it('applies nothing for an empty patch', () => {
    const written: string[] = [];
    applyProposalPatch({}, (field) => written.push(field));

    expect(written).toEqual([]);
  });
});

describe('draftFor', () => {
  it('publishes exactly the fields the draft type declares', () => {
    // The boundary that keeps a key's plaintext out of the assistant. The
    // create dialog holds the one copy that will ever exist at the same moment
    // it publishes this, so what leaves has to be enumerated rather than spread.
    const draft = draftFor({
      name: 'ci',
      scopes: ['chat'],
      rate_limit_rpm: 60,
      quota_tokens_per_day: 1000,
      allowed_cidrs_text: '203.0.113.0/24',
      expires_at: '2026-10-27',
    });

    expect(Object.keys(draft).sort()).toEqual([
      'allowed_cidrs',
      'expires_at',
      'name',
      'quota_tokens_per_day',
      'rate_limit_rpm',
      'scopes',
    ]);
  });

  it('keeps a half-typed form readable rather than refusing it', () => {
    // A draft is published precisely when the form does not validate — that is
    // usually why help is being asked for. An empty rate limit is a fact worth
    // sending, not a reason to send nothing.
    const draft = draftFor({ name: '', rate_limit_rpm: '' });

    expect(draft.rate_limit_rpm).toBe('');
    expect(draft.scopes).toEqual([]);
  });
});

describe('the default capability, which the strict schema had to be told about', () => {
  it('does not drop the whole card when a proposal carries it', () => {
    // `proposalFieldsSchema` is `.strict()`, and the backend's proposal shape
    // is `UpdateApiKeyRequest` — so the day that model gained the field, a
    // proposal the backend happily validated became a card this parse threw
    // away entire, taking the recommendations beside it with it.
    const found = readProposalFrame({
      proposal: {
        action: 'create',
        fields: { scopes: ['chat', 'code'], default_capability: 'code' },
        rationale: 'They asked for it to just work.',
      },
    });

    expect(found).not.toBeNull();
    expect(found?.fields.default_capability).toBe('code');
  });

  it('carries an explicit null, which is the card that withdraws a default', () => {
    const found = readProposalFrame({
      proposal: {
        action: 'update',
        key_id: 'k1',
        fields: { default_capability: null },
        rationale: 'Refusing again will show what the client is sending.',
      },
    });

    expect(found?.fields.default_capability).toBeNull();
  });

  it('turns that null into the word the select holds', () => {
    // The form cannot hold `null` here: an empty value renders the
    // placeholder, so "refuse" is a named option.
    const patch = proposalToFormPatch({
      default_capability: null,
    } as ProposalFields);

    expect(patch.default_capability).toBe(NO_DEFAULT);
  });

  it('leaves the field alone when the proposal did not name it', () => {
    const patch = proposalToFormPatch({ name: 'ci' } as ProposalFields);

    expect('default_capability' in patch).toBe(false);
  });

  it('applies through the allowlist rather than being silently dropped', () => {
    const written: Record<string, unknown> = {};
    applyProposalPatch({ default_capability: 'code' }, (field, value) => {
      written[field] = value;
    });

    expect(written.default_capability).toBe('code');
  });

  it('publishes the setting in the draft, and omits it when it is "refuse"', () => {
    // Omitted rather than sent as the sentinel: the backend's draft model
    // forbids unknown keys and knows nothing of a capability called "refuse".
    expect(draftFor({ default_capability: 'code' }).default_capability).toBe(
      'code',
    );
    expect(
      'default_capability' in draftFor({ default_capability: NO_DEFAULT }),
    ).toBe(false);
  });
});
