import { describe, expect, it } from 'vitest';

import {
  frameFinishReason,
  frameText,
  streamFrameSchema,
} from '@/features/chat/schema';

describe('streamFrameSchema and frame accessors', () => {
  // The regression this schema exists for: the OpenAI envelope must survive
  // parsing. An earlier flat-only schema stripped `choices` as an unknown key,
  // so every real frame parsed into an empty object and no reply ever rendered.
  it('preserves the OpenAI envelope through parsing', () => {
    const parsed = streamFrameSchema.parse({
      choices: [{ index: 0, delta: { role: 'assistant', content: 'Hello' } }],
    });
    expect(frameText(parsed)).toBe('Hello');
  });

  it('reads the flat delta and content spellings', () => {
    expect(frameText(streamFrameSchema.parse({ delta: 'yo' }))).toBe('yo');
    expect(frameText(streamFrameSchema.parse({ content: 'sup' }))).toBe('sup');
  });

  it('prefers the envelope over the flat spelling when both are present', () => {
    const parsed = streamFrameSchema.parse({
      choices: [{ delta: { content: 'envelope' } }],
      delta: 'flat',
    });
    expect(frameText(parsed)).toBe('envelope');
  });

  it('yields empty text for a frame carrying none', () => {
    expect(frameText(streamFrameSchema.parse({}))).toBe('');
  });

  it('reads finish_reason from either spelling', () => {
    expect(
      frameFinishReason(streamFrameSchema.parse({ choices: [{ finish_reason: 'stop' }] })),
    ).toBe('stop');
    expect(frameFinishReason(streamFrameSchema.parse({ finish_reason: 'length' }))).toBe('length');
    expect(frameFinishReason(streamFrameSchema.parse({}))).toBeNull();
  });

  it('accepts both error spellings', () => {
    expect(streamFrameSchema.safeParse({ error: 'boom' }).success).toBe(true);
    expect(streamFrameSchema.safeParse({ error: { message: 'boom' } }).success).toBe(true);
  });

  it('rejects a non-object frame', () => {
    expect(streamFrameSchema.safeParse(5).success).toBe(false);
    expect(streamFrameSchema.safeParse('nope').success).toBe(false);
  });
});
