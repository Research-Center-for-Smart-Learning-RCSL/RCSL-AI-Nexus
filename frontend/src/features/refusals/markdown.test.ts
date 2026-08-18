import { describe, expect, it } from 'vitest';

import { refusalToMarkdown, refusalsToMarkdown } from '@/features/refusals/markdown';
import type { Refusal } from '@/features/refusals/schema';

const REFUSAL: Refusal = {
  id: 'r1',
  at: '2026-08-18T00:40:46.354Z',
  code: 'context_too_long',
  status: 413,
  actor_id: 'u1',
  actor_display: 'teacher@example.test',
  api_key_id: '979e405245fd70d8',
  surface: 'gateway',
  method: 'POST',
  path: '/v1/chat/completions',
  request_id: 'req_ab40e7554c4d42c0',
  message: 'This input is 125,340 tokens against a limit of 122,880.',
  figures: {
    estimated: 125340,
    limit: 122880,
    basis: 'tokenizer',
    composition: '~125329 in 1 messages (largest turn ~125329, 100% of the whole)',
  },
};

describe('refusalToMarkdown', () => {
  it('quotes the sentence the caller was actually given', () => {
    // Reproduced rather than paraphrased: what somebody pastes into a ticket
    // has to be the thing they were told, or the person reading it is
    // debugging a different message.
    expect(refusalToMarkdown(REFUSAL)).toContain(
      '> This input is 125,340 tokens against a limit of 122,880.',
    );
  });

  it('carries the request id in full, where the table truncates it', () => {
    const md = refusalToMarkdown(REFUSAL);
    expect(md).toContain('`req_ab40e7554c4d42c0`');
    expect(md).toContain('| when | 2026-08-18T00:40:46.354Z |');
  });

  it('puts the composition on its own line rather than in a cell', () => {
    // It is a sentence naming which of three remedies applies, and it is the
    // field that ended the 2026-08-17 incident.
    const md = refusalToMarkdown(REFUSAL);
    expect(md).toContain('**Where it went:** ~125329 in 1 messages');
    expect(md).not.toContain('| where it went |');
  });

  it('carries the remedy for a code that has one, and nothing for one that does not', () => {
    expect(refusalToMarkdown(REFUSAL)).toContain('**What to try:**');
    expect(refusalToMarkdown({ ...REFUSAL, code: 'something_new' })).not.toContain(
      '**What to try:**',
    );
  });

  it('renders a figure nobody has written a label for', () => {
    /**
     * The set differs per code and four more errors are specified to carry
     * one. A builder that named its figures would drop the next one silently,
     * which on a paste means the number somebody needed is simply absent.
     */
    const md = refusalToMarkdown({
      ...REFUSAL,
      figures: { some_future_figure: 42 },
    });
    expect(md).toContain('| some_future_figure | 42 |');
  });

  it('escapes a pipe so one value cannot shift every column after it', () => {
    const md = refusalToMarkdown({ ...REFUSAL, figures: { reason: 'a|b' } });
    expect(md).toContain('| reason | a\\|b |');
  });

  it('renders a list figure as code spans', () => {
    const md = refusalToMarkdown({
      ...REFUSAL,
      code: 'capability_not_issued',
      figures: { capability: 'code', available: ['chat', 'embedding'] },
    });
    expect(md).toContain('| available | `chat`, `embedding` |');
  });

  it('names the account and keeps the id, so a paste is both readable and quotable', () => {
    // A paste is read by somebody who was not looking at the screen, and
    // quoted in an investigation that needs the handle.
    const md = refusalToMarkdown(REFUSAL, { account: 'Isaries' });
    expect(md).toContain('| account | Isaries (u1) |');
  });

  it('falls back to the account id when no name could be resolved', () => {
    // A deleted account, or a reader whose page never fetched the list.
    expect(refusalToMarkdown(REFUSAL)).toContain('| account | u1 |');
  });

  it('omits the API key row when the caller was a person', () => {
    expect(refusalToMarkdown({ ...REFUSAL, api_key_id: null })).not.toContain('| api key |');
  });
});

describe('refusalsToMarkdown', () => {
  it('says what was left out, because a page is usually not the whole', () => {
    /**
     * Three refusals out of fifty-seven pasted with no note read as the whole
     * of what happened — and this screen narrows by default for anyone without
     * `refusal:read_all`. Saying so is the difference between evidence and a
     * misleading excerpt.
     */
    const md = refusalsToMarkdown([REFUSAL], {
      total: 57,
      scopedToSelf: true,
      filter: 'code context_too_long',
    });

    expect(md).toContain('1 of 57 shown, from one account and its API keys');
    expect(md).toContain('filtered by code context_too_long');
  });

  it('says when it is showing every account', () => {
    const md = refusalsToMarkdown([REFUSAL], { total: 1, scopedToSelf: false });
    expect(md).toContain('from all accounts.');
  });

  it('separates the entries so a reader can tell where one ends', () => {
    const md = refusalsToMarkdown([REFUSAL, { ...REFUSAL, id: 'r2' }], {
      total: 2,
      scopedToSelf: false,
    });
    expect(md.match(/^---$/gm)).toHaveLength(2);
    expect(md.match(/^## 413 `context_too_long`$/gm)).toHaveLength(2);
  });
});

describe('a hand-picked paste', () => {
  it('says it is a choice rather than a window', () => {
    /**
     * Two claims that must not read alike. A whole page tells the reader how
     * much of the matches they are holding and they can see the rest by
     * paging. A selection is three rows somebody chose out of fifty for a
     * reason the paste does not carry — which of the other forty-seven were
     * passed over, and why, is nowhere in the numbers.
     */
    const md = refusalsToMarkdown([REFUSAL], {
      total: 120,
      scopedToSelf: false,
      picked: true,
    });

    expect(md).toContain('1 hand-picked out of 120 matching, from all accounts.');
    expect(md).not.toContain('1 of 120 shown');
  });

  it('reads as a window when it is one', () => {
    const md = refusalsToMarkdown([REFUSAL], { total: 120, scopedToSelf: false });

    expect(md).toContain('1 of 120 shown, from all accounts.');
  });
});
