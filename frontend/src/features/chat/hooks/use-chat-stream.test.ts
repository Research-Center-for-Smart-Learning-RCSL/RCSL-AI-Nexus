import { describe, expect, it } from 'vitest';

import {
  chatRequestFor,
  historyFor,
  type ChatTurn,
} from '@/features/chat/hooks/use-chat-stream';

const turn = (partial: Partial<ChatTurn> & Pick<ChatTurn, 'role'>): ChatTurn => ({
  id: crypto.randomUUID(),
  content: '',
  ...partial,
});

describe('historyFor', () => {
  it('replays the transcript and appends the new prompt', () => {
    const history = historyFor(
      [
        turn({ role: 'user', content: 'hello' }),
        turn({ role: 'assistant', content: 'hi' }),
      ],
      'next',
    );

    expect(history).toEqual([
      { role: 'user', content: 'hello' },
      { role: 'assistant', content: 'hi' },
      { role: 'user', content: 'next' },
    ]);
  });

  it('never sends reasoning back as history', () => {
    // Scratch work, not the answer. Replaying it feeds the model its own
    // deliberation and multiplies the prompt on every later turn.
    const history = historyFor(
      [turn({ role: 'assistant', content: 'the answer', reasoning: 'long deliberation' })],
      'next',
    );

    expect(history[0]).toEqual({ role: 'assistant', content: 'the answer' });
    expect(JSON.stringify(history)).not.toContain('deliberation');
  });

  it('drops a turn that produced only reasoning', () => {
    // The 2026-07-27 case: the whole budget went to thinking and no answer
    // started. The turn is kept on screen, but sending `content: ''` would put
    // an empty assistant message into the prompt template for this request and
    // every one after it.
    const history = historyFor(
      [
        turn({ role: 'user', content: 'a hard question' }),
        turn({ role: 'assistant', content: '', reasoning: 'thought about it' }),
      ],
      'next',
    );

    expect(history).toEqual([
      { role: 'user', content: 'a hard question' },
      { role: 'user', content: 'next' },
    ]);
  });

  it('drops a turn that failed before its first token', () => {
    const history = historyFor(
      [turn({ role: 'assistant', content: '', error: 'Request failed with status 500' })],
      'next',
    );

    expect(history).toEqual([{ role: 'user', content: 'next' }]);
  });
});

describe('chatRequestFor', () => {
  const messages = [{ role: 'user' as const, content: 'hi' }];

  it('sends the toggle in both directions, so the control cannot lie', () => {
    // Omitting the field when checked meant that under OLLAMA_THINKING=false
    // the box read "on" while the server applied "off", with no way to correct
    // it from the panel. Safe to send: the adapter maps `true` to sending no
    // `think` field to the runtime, which is what protects a non-thinking model.
    expect(chatRequestFor('chat', messages, true)).toEqual({
      capability: 'chat',
      messages,
      think: true,
    });
    expect(chatRequestFor('chat', messages, false)).toEqual({
      capability: 'chat',
      messages,
      think: false,
    });
  });

  it('omits the field only when the caller expressed no preference', () => {
    expect('think' in chatRequestFor('chat', messages, undefined)).toBe(false);
    expect('think' in chatRequestFor('chat', messages)).toBe(false);
  });

  it('carries the capability and messages through unchanged', () => {
    expect(chatRequestFor('code', messages)).toEqual({ capability: 'code', messages });
  });
});
