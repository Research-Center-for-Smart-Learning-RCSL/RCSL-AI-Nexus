import { describe, expect, it } from 'vitest';

import { auditLogSchema } from '@/features/logs/schema';

describe('auditLogSchema', () => {
  it('parses a page with entries', () => {
    const page = auditLogSchema.parse({
      entries: [
        {
          id: 'e1',
          actor_id: 'a1',
          actor_display: 'admin@x',
          actor_source: 'local',
          action: 'user.invited',
          target: null,
          outcome: 'success',
          detail: { login: 'b@x' },
          at: '2026-07-25T12:00:00Z',
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    expect(page.entries[0].detail.login).toBe('b@x');
  });

  it('rejects a non-string detail value, catching a backend contract drift', () => {
    expect(() =>
      auditLogSchema.parse({
        entries: [
          {
            id: 'e1',
            actor_id: 'a1',
            actor_display: 'admin@x',
            actor_source: 'local',
            action: 'x',
            target: null,
            outcome: 'success',
            detail: { count: 3 },
            at: '2026-07-25T12:00:00Z',
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      }),
    ).toThrow();
  });
});
