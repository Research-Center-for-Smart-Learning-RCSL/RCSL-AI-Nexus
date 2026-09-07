import { describe, expect, it } from 'vitest';

import { usageAnalyticsSchema } from '@/features/usage/schema';

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
