import { describe, expect, it } from 'vitest';

import { usageAnalyticsSchema, usageRecordSchema } from '@/features/usage/schema';

describe('usageAnalyticsSchema', () => {
  it('parses totals and per-capability series', () => {
    const data = usageAnalyticsSchema.parse({
      bucket: 'hour',
      since: '2026-07-24T12:00:00Z',
      until: '2026-07-25T12:00:00Z',
      totals: [{ t: '2026-07-25T11:00:00Z', requests: 3, tokens: 18 }],
      by_capability: [
        { capability: 'chat', points: [{ t: '2026-07-25T11:00:00Z', requests: 2, tokens: 15 }] },
      ],
      compaction: { requests: 0, tokens_removed: 0, by_tier: [] },
    });
    expect(data.bucket).toBe('hour');
    expect(data.by_capability[0].capability).toBe('chat');
  });

  it('keeps tier 0 as a tier rather than as an absence', () => {
    const data = usageAnalyticsSchema.parse({
      bucket: 'hour',
      since: '2026-07-24T12:00:00Z',
      until: '2026-07-25T12:00:00Z',
      totals: [],
      by_capability: [],
      compaction: {
        requests: 4,
        tokens_removed: 12_000,
        by_tier: [
          { tier: 0, requests: 3 },
          { tier: 2, requests: 1 },
        ],
      },
    });
    // Tier 0 trims tool definitions and is a real compaction. Anything here
    // that treated the number as falsy would drop three of the four.
    expect(data.compaction.by_tier[0].tier).toBe(0);
    expect(data.compaction.requests).toBe(4);
  });

  it('rejects an unknown bucket unit', () => {
    expect(() =>
      usageAnalyticsSchema.parse({
        bucket: 'week',
        since: '2026-07-24T12:00:00Z',
        until: '2026-07-25T12:00:00Z',
        totals: [],
        by_capability: [],
      }),
    ).toThrow();
  });
});

describe('usageRecordSchema', () => {
  const row = {
    id: 'u1',
    at: '2026-10-09T00:00:00Z',
    actor_id: 'a1',
    api_key_id: null,
    capability: 'chat',
    requested_capability: null,
    model_alias: 'qwen7b',
    tokens: 0,
    prompt_tokens: 40,
    latency_ms: 0,
    completed: false,
    compaction_tier: null,
    tokens_before_compaction: null,
    tokens_after_compaction: null,
    prompt_eval_ms: null,
    eval_ms: null,
    load_ms: null,
  };

  it('reads a direct-path row as having no source', () => {
    const data = usageRecordSchema.parse({
      ...row,
      totals_source: null,
      prompt_tokens_basis: null,
      runtime_completed: null,
    });
    expect(data.totals_source).toBeNull();
  });

  it('keeps where an agent-billed figure came from', () => {
    const data = usageRecordSchema.parse({
      ...row,
      totals_source: 'unavailable',
      prompt_tokens_basis: 'estimate',
      runtime_completed: false,
    });
    expect(data.totals_source).toBe('unavailable');
    expect(data.prompt_tokens_basis).toBe('estimate');
  });

  it('keeps the runtime timings, and leaves unreported ones null', () => {
    const data = usageRecordSchema.parse({
      ...row,
      totals_source: 'runtime_final',
      prompt_tokens_basis: 'runtime_final',
      runtime_completed: true,
      prompt_eval_ms: 28940,
      eval_ms: 18,
    });
    expect(data.prompt_eval_ms).toBe(28940);
    expect(data.load_ms).toBeNull();
  });

  it('rejects a source the backend never writes', () => {
    expect(() =>
      usageRecordSchema.parse({
        ...row,
        totals_source: 'guessed',
        prompt_tokens_basis: null,
        runtime_completed: null,
      }),
    ).toThrow();
  });
});
