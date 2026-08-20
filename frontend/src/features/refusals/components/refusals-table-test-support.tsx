import { beforeEach, vi } from 'vitest';
import { screen } from '@testing-library/react';

import { RefusalsTable } from '@/features/refusals/components/refusals-table';
import type { Refusal, RefusalFilters } from '@/features/refusals/schema';
import type { User } from '@/features/users/schema';

/**
 * The three things an operator could not do on this screen.
 *
 * It could copy one refusal or copy fifty, and an investigation is usually
 * three — the 413 and the two 409s that followed it. It could narrow to one
 * account only by uuid, and nothing on the screen is a uuid a person could
 * type. And it could not ask about a time at all, though the backend had
 * filtered on one since the table existed.
 *
 * These run as a reader with `refusal:read_all`, because that is the reader
 * every one of the three belongs to.
 */

function refusal(over: Partial<Refusal> & { id: string }): Refusal {
  return {
    at: '2026-08-17T19:16:00.000Z',
    code: 'context_too_long',
    status: 413,
    actor_id: 'u1',
    actor_display: 'teacher@example.test',
    api_key_id: null,
    surface: 'admin',
    method: 'POST',
    path: '/admin/chat',
    request_id: 'req_one',
    message: 'This input is 125,340 tokens against a limit of 122,880.',
    figures: {},
    ...over,
  };
}

export const ROWS = [
  refusal({ id: 'r1' }),
  refusal({ id: 'r2', code: 'quota_exceeded', status: 429, request_id: 'req_two' }),
  refusal({
    id: 'r3',
    code: 'rate_limited',
    status: 429,
    actor_id: 'u2',
    actor_display: 'student@example.test',
    request_id: 'req_three',
  }),
];

function user(id: string, display_name: string, login: string): User {
  return {
    id,
    login,
    display_name,
    tailscale_login: null,
    has_local_credentials: true,
    has_totp: true,
    role: 'user',
    debug_logging_until: null,
    created_at: null,
  };
}

const USERS = [
  user('11111111-2222-3333-4444-555555555555', 'Wu Mei', 'wu@example.test'),
  user('66666666-7777-8888-9999-000000000000', 'Chen', 'chen@example.test'),
];

/** The last filters the table asked the server for. */
export let asked: RefusalFilters;

vi.mock('@/features/refusals/hooks/use-refusals', () => ({
  useRefusals: (filters: RefusalFilters) => {
    asked = filters;
    return {
      data: { entries: ROWS, total: 120, limit: 50, offset: filters.offset, scoped_to_self: false },
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: vi.fn(),
    };
  },
}));

vi.mock('@/features/users/hooks/use-users', () => ({
  useUsers: () => ({ data: USERS }),
}));

export const written: string[] = [];

beforeEach(() => {
  written.length = 0;
  Object.assign(navigator, {
    clipboard: {
      writeText: (text: string) => {
        written.push(text);
        return Promise.resolve();
      },
    },
  });
});

export function tickFor(row: Refusal): HTMLElement {
  return screen.getByLabelText(new RegExp(`^Select the ${row.code} refusal from`));
}

export function TestRefusalsTable() {
  return <RefusalsTable />;
}
