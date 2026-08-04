import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { EditUserDialog } from '@/features/users/components/edit-user-dialog';
import type { User } from '@/features/users/schema';

/**
 * The screen that did not exist.
 *
 * `PATCH /admin/users/{id}` worked, `updateUser` wrapped it, `useUpdateUser`
 * wrapped that — and the hook had no caller anywhere in the application. A
 * display name was therefore whatever it was given at invitation and could
 * never be corrected, and no administrator could promote anybody, which is the
 * one operation that lets a second administrator exist. Both were reported on
 * 2026-08-04 as separate problems; they were the same absent dialog.
 */

const updateUser = vi.fn();
// `listRoles` too: the role picker fetches the catalogue so it can show what
// each role actually grants, and a module mock that omits an export the
// component imports fails at import time rather than at the assertion.
const listRoles = vi.fn(async () => [
  { role: 'user', scopes: ['chat:use'] },
  { role: 'admin', scopes: ['chat:use', 'user:write'] },
]);
vi.mock('@/features/users/api', () => ({
  updateUser: (...args: unknown[]) => updateUser(...args),
  listRoles: () => listRoles(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const SOMEONE: User = {
  id: 'u-1',
  login: 'person@ntnu.edu.tw',
  display_name: 'Old Name',
  tailscale_login: null,
  has_local_credentials: true,
  has_totp: true,
  role: 'user',
  debug_logging_until: null,
  created_at: '2026-08-01T00:00:00Z',
};

beforeEach(() => {
  updateUser.mockReset();
  updateUser.mockResolvedValue({ ...SOMEONE, display_name: 'New Name' });
});

describe('editing a user', () => {
  it('saves a changed display name', async () => {
    const user = userEvent.setup();
    render(
      <EditUserDialog user={SOMEONE} isSelf={false} onClose={() => {}} />,
      { wrapper: Wrapper },
    );

    const field = screen.getByLabelText('Display name');
    expect((field as HTMLInputElement).value).toBe('Old Name');

    await user.clear(field);
    await user.type(field, 'New Name');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(updateUser).toHaveBeenCalledWith(
        'u-1',
        expect.objectContaining({ display_name: 'New Name' }),
      ),
    );
  });

  it('closes once the save has succeeded, not before', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <EditUserDialog user={SOMEONE} isSelf={false} onClose={onClose} />,
      { wrapper: Wrapper },
    );

    await user.clear(screen.getByLabelText('Display name'));
    await user.type(screen.getByLabelText('Display name'), 'New Name');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(updateUser).toHaveBeenCalled();
  });

  it('promotes another user, which is how a second administrator comes to exist', async () => {
    const user = userEvent.setup();
    render(
      <EditUserDialog user={SOMEONE} isSelf={false} onClose={() => {}} />,
      { wrapper: Wrapper },
    );

    await user.click(screen.getByRole('combobox'));
    await user.click(screen.getByRole('option', { name: 'Platform administrator' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(updateUser).toHaveBeenCalledWith(
        'u-1',
        expect.objectContaining({ role: 'admin' }),
      ),
    );
  });

  it('will not let you change your own role, matching what the backend refuses', async () => {
    render(
      <EditUserDialog user={SOMEONE} isSelf onClose={() => {}} />,
      { wrapper: Wrapper },
    );

    expect(screen.getByRole('combobox')).toBeDisabled();
  });
});
