import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { UserTable } from '@/features/users/components/user-table';
import type { User } from '@/features/users/schema';

/**
 * The debug window on an account, which is one button whose whole behaviour is
 * a toggle read off a timestamp.
 *
 * Worth a test because of how the user half of this switch shipped: the column
 * existed from the first migration, `identity.py` read it and granted on it,
 * the response schema carried it and this table displayed it — and nothing
 * could set it, for twelve days, looking complete from every direction. The
 * button is the missing writer, and the way it can now go quietly wrong is
 * that an open window re-opens instead of closing, which reads as a working
 * button and leaves the window open indefinitely.
 */

const users: User[] = [];
const setDebugWindow = vi.fn();

vi.mock('@/features/users/hooks/use-users', () => ({
  useUsers: () => ({ data: users, isLoading: false, error: null, refetch: vi.fn() }),
  useDeleteUser: () => ({ mutateAsync: vi.fn() }),
  useIssueInvitation: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useIssuePasswordReset: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSetUserDebugWindow: () => ({ mutate: setDebugWindow }),
}));

// Dialogs mounted beside the table; neither is under test here.
vi.mock('@/features/users/components/invite-user-dialog', () => ({
  InviteUserDialog: () => null,
}));
vi.mock('@/features/users/components/edit-user-dialog', () => ({
  EditUserDialog: () => null,
}));

vi.mock('@/lib/session', () => ({
  useSession: () => ({
    me: { id: 'admin-1' },
    can: (scope: string) => scope === 'user:write',
  }),
}));

function listedUser(debugUntil: string | null): User {
  return {
    id: 'u2',
    login: 'someone@example.test',
    display_name: 'Someone',
    tailscale_login: null,
    has_local_credentials: true,
    has_totp: true,
    role: 'user',
    debug_logging_until: debugUntil,
    created_at: '2026-07-26T00:00:00Z',
  };
}

function listing(debugUntil: string | null) {
  users.length = 0;
  users.push(listedUser(debugUntil));
}

beforeEach(() => {
  setDebugWindow.mockClear();
  vi.useRealTimers();
});

describe('the debug window on an account', () => {
  it('opens for an hour when the window is closed', async () => {
    listing(null);
    const user = userEvent.setup();
    render(<UserTable />);

    await user.click(screen.getByRole('button', { name: 'Debug' }));

    expect(setDebugWindow).toHaveBeenCalledWith({ userId: 'u2', minutes: 60 });
  });

  it('closes rather than re-opening when the window is already open', async () => {
    // The defect this test exists for. A button that re-opens on every press
    // is indistinguishable from one that closes, until somebody notices the
    // window never actually expired.
    listing(new Date(Date.now() + 30 * 60_000).toISOString());
    const user = userEvent.setup();
    render(<UserTable />);

    await user.click(screen.getByRole('button', { name: /^Debug 3\d+m$/ }));

    expect(setDebugWindow).toHaveBeenCalledWith({ userId: 'u2', minutes: 0 });
  });

  it('shows the time remaining, so an open window is visible from the table', () => {
    listing(new Date(Date.now() + 30 * 60_000).toISOString());
    render(<UserTable />);

    expect(screen.getByRole('button', { name: /^Debug 3\d+m$/ })).toBeInTheDocument();
  });

  it('treats an expired timestamp as closed', () => {
    // Time-boxed means the box closes by itself. A past expiry must read as no
    // window at all rather than as an open one nobody can close, which is what
    // a truthiness check on the column alone would produce.
    listing(new Date(Date.now() - 60_000).toISOString());
    render(<UserTable />);

    expect(screen.getByRole('button', { name: 'Debug' })).toBeInTheDocument();
  });
});
