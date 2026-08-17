import { describe, expect, it } from 'vitest';

import { refusalPageSchema, refusalSchema, remedyFor } from '@/features/refusals/schema';

const REFUSAL = {
  id: 'r1',
  at: '2026-08-17T19:16:00Z',
  code: 'context_too_long',
  status: 413,
  actor_id: 'u1',
  actor_display: 'teacher@example.test',
  api_key_id: 'k_abc',
  surface: 'gateway',
  method: 'POST',
  path: '/v1/chat/completions',
  request_id: 'req_9f2a',
  message: 'This input is 140,059 tokens against a limit of 122,880.',
  figures: {
    estimated: 140059,
    limit: 122880,
    basis: 'tokenizer',
    composition: '~17189 in 4 messages, ~0 in prior tool calls, ~122870 in 286 tool definitions',
  },
};

describe('refusalSchema', () => {
  it('parses a page and keeps the figures it was not told the shape of', () => {
    /**
     * The set differs per code and is the part most likely to grow. A schema
     * that modelled it would drop a new figure silently, which on this screen
     * means the number somebody needed is simply absent.
     */
    const page = refusalPageSchema.parse({
      entries: [REFUSAL],
      total: 1,
      limit: 50,
      offset: 0,
      scoped_to_self: true,
    });

    expect(page.entries[0].figures.basis).toBe('tokenizer');
    expect(page.entries[0].figures.composition).toContain('286 tool definitions');
  });

  it('accepts a refusal that carries no figures at all', () => {
    // Most codes carry none, and a 500 carries none by design.
    const parsed = refusalSchema.parse({ ...REFUSAL, code: 'internal_error', status: 500, figures: {} });
    expect(parsed.figures).toEqual({});
  });

  it('keeps request_id nullable, because a refusal before routing has none', () => {
    expect(refusalSchema.parse({ ...REFUSAL, request_id: null }).request_id).toBeNull();
  });
});

describe('remedyFor', () => {
  it('names the three remedies a 413 has, since only one of them is "start again"', () => {
    const remedy = remedyFor('context_too_long');
    expect(remedy).toContain('tool list');
    expect(remedy).toContain('resent every turn');
  });

  it('says nothing rather than something generic for a code nobody has thought about', () => {
    /**
     * "Try again or contact an administrator" implies the platform knows what
     * to do about a refusal it has no advice for, and the row already carries
     * the sentence the caller was actually given.
     */
    expect(remedyFor('some_error_added_next_year')).toBeNull();
  });
});
