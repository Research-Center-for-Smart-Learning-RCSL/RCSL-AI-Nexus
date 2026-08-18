import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

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

const ROWS = [
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
let asked: RefusalFilters;

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

const written: string[] = [];

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

function tickFor(row: Refusal): HTMLElement {
  return screen.getByLabelText(new RegExp(`^Select the ${row.code} refusal from`));
}

describe('copying some of the rows rather than all or one', () => {
  it('copies the page when nothing is ticked', async () => {
    render(<RefusalsTable />);

    expect(screen.getByRole('button', { name: /Copy this page/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Copy this page/ }));
    await vi.waitFor(() => expect(written).toHaveLength(1));

    expect(written[0]).toContain('3 of 120 shown');
  });

  it('copies only the ticked rows, and counts them on the button', async () => {
    render(<RefusalsTable />);

    fireEvent.click(tickFor(ROWS[0]));
    fireEvent.click(tickFor(ROWS[2]));

    fireEvent.click(screen.getByRole('button', { name: /Copy 2 selected/ }));
    await vi.waitFor(() => expect(written).toHaveLength(1));

    expect(written[0]).toContain('`req_one`');
    expect(written[0]).toContain('`req_three`');
    expect(written[0]).not.toContain('`req_two`');
  });

  it('says a hand-picked paste is one', async () => {
    /**
     * Two rows out of a hundred and twenty, pasted into a ticket with no note,
     * read as the whole of what happened. A whole page at least tells the
     * reader how much of the window they are holding; a selection is a
     * *choice*, and nothing in the numbers says which of the rest were passed
     * over or why. It is the more misleading of the two, so it is the one that
     * has to say so.
     */
    render(<RefusalsTable />);

    fireEvent.click(tickFor(ROWS[0]));
    fireEvent.click(screen.getByRole('button', { name: /Copy 1 selected/ }));
    await vi.waitFor(() => expect(written).toHaveLength(1));

    expect(written[0]).toContain('1 hand-picked out of 120 matching');
  });

  it('ticks and clears the whole page from the header', () => {
    render(<RefusalsTable />);

    fireEvent.click(screen.getByLabelText('Select every refusal on this page'));
    expect(screen.getByRole('button', { name: /Copy 3 selected/ })).toBeTruthy();

    fireEvent.click(screen.getByLabelText('Clear the selection'));
    expect(screen.getByRole('button', { name: /Copy this page/ })).toBeTruthy();
  });

  it('shows the header box as part-way when only some rows are ticked', () => {
    render(<RefusalsTable />);

    fireEvent.click(tickFor(ROWS[1]));

    const all = screen.getByLabelText('Select every refusal on this page') as HTMLInputElement;
    expect(all.indeterminate).toBe(true);
    expect(all.checked).toBe(false);
  });

  it('drops the selection when the rows underneath it change', () => {
    // A tick means "this refusal, the one I am looking at". Carried across a
    // filter change it leaves the button offering a count of rows the reader
    // can no longer see and cannot check.
    render(<RefusalsTable />);

    fireEvent.click(tickFor(ROWS[0]));
    expect(screen.getByRole('button', { name: /Copy 1 selected/ })).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/Filter by error code/), {
      target: { value: 'quota_exceeded' },
    });

    expect(screen.getByRole('button', { name: /Copy this page/ })).toBeTruthy();
  });
});

describe('narrowing to one account by the name the screen shows', () => {
  it('offers the accounts this reader can list as completions', () => {
    render(<RefusalsTable />);

    const names = [...document.querySelectorAll('#refusal-account-names option')].map(
      (option) => (option as HTMLOptionElement).value,
    );
    expect(names).toEqual(['Chen', 'Wu Mei']);
  });

  it('sends a name it can resolve as that account’s id', () => {
    render(<RefusalsTable />);

    fireEvent.change(screen.getByLabelText(/Show one account's refusals/), {
      target: { value: 'Wu Mei' },
    });

    expect(asked.actor_id).toBe('11111111-2222-3333-4444-555555555555');
    expect(asked.actor_display).toBeUndefined();
  });

  it('sends a name it cannot resolve as a search of the recorded names', () => {
    // The deleted account, whose name survives on the row and nowhere else.
    render(<RefusalsTable />);

    fireEvent.change(screen.getByLabelText(/Show one account's refusals/), {
      target: { value: 'departed' },
    });

    expect(asked.actor_display).toBe('departed');
    expect(asked.actor_id).toBeUndefined();
  });

  it('filters by id when a row’s own account is clicked, and shows the name', () => {
    render(<RefusalsTable />);

    fireEvent.click(screen.getAllByRole('button', { name: /student@example.test/ })[0]);

    // The row knows exactly whose it is, so the exact filter is the right one
    // — it also catches this account's gateway refusals, whose recorded name
    // is the key's handle rather than the person's.
    expect(asked.actor_id).toBe('u2');
    expect(asked.actor_display).toBeUndefined();
  });
});

describe('narrowing to when it happened', () => {
  it('asks for no window until somebody sets one', () => {
    render(<RefusalsTable />);

    expect(asked.since).toBeUndefined();
    expect(asked.until).toBeUndefined();
  });

  it('sends the instant a typed local time names', () => {
    render(<RefusalsTable />);

    fireEvent.change(screen.getByLabelText('From, inclusive'), {
      target: { value: '2026-08-17T19:00' },
    });

    expect(asked.since).toBe(new Date('2026-08-17T19:00').toISOString());
  });

  it('fills the boxes from a preset rather than replacing them', () => {
    // So the reader can see what "last hour" meant and then move it — and so
    // the boundary stays put while they page through what it matched.
    render(<RefusalsTable />);

    fireEvent.click(screen.getByRole('button', { name: 'Today' }));

    const from = screen.getByLabelText('From, inclusive') as HTMLInputElement;
    expect(from.value).toMatch(/T00:00$/);
    expect(asked.since).toBeDefined();
  });

  it('clears both ends at once', () => {
    render(<RefusalsTable />);

    fireEvent.change(screen.getByLabelText('Before, exclusive'), {
      target: { value: '2026-08-18T00:00' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));

    expect(asked.until).toBeUndefined();
  });
});

describe('what the paste says it is', () => {
  it('names every filter in force, not the two this screen started with', async () => {
    /**
     * The account filter was added without being added to the subtitle, so a
     * page copied while narrowed to one person was headed "from all accounts"
     * — the exact misleading excerpt the exporter was written to prevent,
     * produced by its own caller.
     */
    render(<RefusalsTable />);

    fireEvent.change(screen.getByLabelText(/Show one account's refusals/), {
      target: { value: 'Wu Mei' },
    });
    fireEvent.change(screen.getByLabelText('From, inclusive'), {
      target: { value: '2026-08-17T19:00' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Copy this page/ }));
    await vi.waitFor(() => expect(written).toHaveLength(1));

    expect(written[0]).toContain('account 11111111-2222-3333-4444-555555555555');
    expect(written[0]).toContain(`from ${new Date('2026-08-17T19:00').toISOString()}`);
  });
});
