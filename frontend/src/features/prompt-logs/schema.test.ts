import { describe, expect, it } from 'vitest';

import {
  parseTranscriptTurns,
  promptLogListSchema,
  promptLogSummarySchema,
  promptLogTranscriptSchema,
} from '@/features/prompt-logs/schema';

const SUMMARY = {
  id: 'p1',
  at: '2026-08-08T12:00:00Z',
  actor_id: 'u1',
  api_key_id: 'k_abc',
  capability: 'chat',
  model_alias: 'gemma4-31b-q8',
  request_id: 'req_9f2a',
  finish_reason: 'stop',
  completed: true,
  tool_calls: 0,
  message_chars: 120,
  completion_chars: 340,
  reasoning_chars: 0,
  truncated_fields: [],
};

describe('promptLogSummarySchema', () => {
  it('parses a page', () => {
    const page = promptLogListSchema.parse({
      entries: [SUMMARY],
      total: 1,
      limit: 50,
      offset: 0,
    });
    expect(page.entries[0].request_id).toBe('req_9f2a');
  });

  it('refuses a summary that carries message content', () => {
    /**
     * The disclosure boundary, asserted rather than assumed.
     *
     * The list endpoint must never return prompt text: the whole design of
     * this feature is that finding a conversation and reading one are separate
     * requests, and only the second writes an audit row. A backend change that
     * started including `completion` here would put message content on a
     * screen without recording that anybody saw it — and, because zod is
     * permissive about unknown keys by default, it would do so silently.
     */
    const strict = promptLogSummarySchema.strict();
    expect(() => strict.parse({ ...SUMMARY, completion: 'the answer' })).toThrow();
  });

  it('keeps null request ids rather than dropping the field', () => {
    // A transcript written before the request-id contextvar was set, or by a
    // path that has none. Declaring it non-nullable would turn that row into a
    // parse failure and an error where a readable transcript should be.
    expect(promptLogSummarySchema.parse({ ...SUMMARY, request_id: null }).request_id).toBeNull();
  });
});

describe('promptLogTranscriptSchema', () => {
  it('parses the full conversation', () => {
    const entry = promptLogTranscriptSchema.parse({
      ...SUMMARY,
      messages: '[{"role":"user","content":"hi"}]',
      completion: 'hello',
      reasoning: '',
    });
    expect(entry.completion).toBe('hello');
  });

  it('requires the text fields, so a truncated response is not read as empty', () => {
    // An absent `completion` and an empty one mean different things: nothing
    // was generated, versus the response did not carry it. Rendering the
    // second as the first would show "the model produced no text" about a
    // conversation that has some.
    expect(() =>
      promptLogTranscriptSchema.parse({ ...SUMMARY, messages: '[]', reasoning: '' }),
    ).toThrow();
  });
});

describe('parseTranscriptTurns', () => {
  it('reads the roles and contents in order', () => {
    const turns = parseTranscriptTurns(
      '[{"role":"system","content":"be brief"},{"role":"user","content":"why"}]',
    );
    expect(turns?.map((t) => t.role)).toEqual(['system', 'user']);
  });

  it('returns null rather than throwing on text that will not parse', () => {
    // The caller falls back to showing the raw string. A transcript that is
    // hard to read is still evidence; an error where the evidence should be is
    // the worse outcome, and this is the screen where that matters most.
    expect(parseTranscriptTurns('{not json')).toBeNull();
  });

  it('returns null for valid JSON that is not a list of turns', () => {
    expect(parseTranscriptTurns('{"role":"user"}')).toBeNull();
  });
});
