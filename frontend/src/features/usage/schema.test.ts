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
    });
    expect(data.bucket).toBe('hour');
    expect(data.by_capability[0].capability).toBe('chat');
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
