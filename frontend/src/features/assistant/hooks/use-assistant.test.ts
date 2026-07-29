import { describe, expect, it } from 'vitest';

import {
  historyFor,
  loadTurns,
  type AssistantTurn,
} from '@/features/assistant/hooks/use-assistant';

/**
 * The transcript rules, which are invisible in the UI and only show up in the
 * request body — so nothing else would catch them being wrong.
 */

function turn(i: number, role: 'user' | 'assistant' = 'user'): AssistantTurn {
  return { id: `t${i}`, role, content: `turn ${i}` };
}

describe('historyFor', () => {
  it('never exceeds the cap the backend declares', () => {
    // The question counts against the same 40 the schema allows, so slicing to
    // 40 and then appending sent 41 and was refused. Twenty exchanges is an
    // ordinary afternoon, and because the transcript is restored from
    // sessionStorage the drawer stayed broken until somebody pressed Clear.
    const many = Array.from({ length: 200 }, (_, i) => turn(i));

    expect(historyFor(many, 'and now?').length).toBeLessThanOrEqual(40);
  });

  it('keeps the most recent turns and puts the question last', () => {
    const messages = historyFor([turn(1), turn(2)], 'and now?');

    expect(messages.at(-1)).toEqual({ role: 'user', content: 'and now?' });
    expect(messages.map((m) => m.content)).toEqual(['turn 1', 'turn 2', 'and now?']);
  });

  it('drops turns with no content', () => {
    // An empty assistant turn would become `{"role":"assistant","content":""}`
    // in the prompt for this request and every later one.
    const empty: AssistantTurn = { id: 'x', role: 'assistant', content: '' };

    expect(historyFor([turn(1), empty], 'go on').map((m) => m.content)).toEqual([
      'turn 1',
      'go on',
    ]);
  });
});

describe('restoring a transcript from sessionStorage', () => {
  function stored(value: unknown): AssistantTurn[] {
    window.sessionStorage.setItem('nexus:assistant:transcript', JSON.stringify(value));
    return loadTurns();
  }

  it('keeps a well-formed turn, proposal included', () => {
    const kept = stored([
      {
        id: 'a1',
        role: 'assistant',
        content: 'Use a narrow key.',
        proposal: {
          action: 'create',
          fields: { scopes: ['chat'] },
          rationale: 'Narrow.',
        },
      },
    ]);

    expect(kept).toHaveLength(1);
    expect(kept[0].proposal?.action).toBe('create');
  });

  it('drops a proposal with no fields rather than rendering it', () => {
    // `ProposalCard` reads `Object.entries(proposal.fields)`, which throws on
    // undefined during render. There is no error boundary above the drawer, so
    // that exception takes down the whole dashboard shell on load — the exact
    // failure this loader exists to prevent.
    expect(stored([{ id: 'a1', role: 'assistant', content: 'hi', proposal: { action: 'create' } }]))
      .toEqual([]);
  });

  it('drops a turn whose role no longer exists', () => {
    // It would be replayed verbatim into the next request and refused there.
    expect(stored([{ id: 'a1', role: 'system', content: 'hi' }])).toEqual([]);
  });

  it('keeps the readable turns beside an unreadable one', () => {
    const kept = stored([
      { id: 'u1', role: 'user', content: 'question' },
      { id: 'x', content: 'no role' },
      { id: 'a1', role: 'assistant', content: 'answer' },
    ]);

    expect(kept.map((t) => t.id)).toEqual(['u1', 'a1']);
  });

  it('survives a stored value that is not a transcript at all', () => {
    expect(stored({ not: 'an array' })).toEqual([]);
    window.sessionStorage.setItem('nexus:assistant:transcript', 'not json');
    expect(loadTurns()).toEqual([]);
  });
});
