import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { RolePicker } from '@/features/users/components/role-picker';

/**
 * The picker offered six role names and nothing else, so choosing between
 * `operator` and `tenant_admin` meant reading `role_authorization.py`. These
 * assert the two layers that replaced that, and they fail differently on
 * purpose: the sentence is copy, the permission list is fetched from the table
 * the backend enforces.
 */

vi.mock('@/features/users/api', () => ({
  listRoles: async () => [
    {
      role: 'operator',
      scopes: ['chat:use', 'model:write', 'node:write', 'routing:write'],
    },
    {
      role: 'tenant_admin',
      // `something:invented` has no entry in SCOPE_LABELS, which is the point:
      // it is what exercises the fallback the last test asserts on.
      scopes: ['chat:use', 'user:write', 'api_key:write_any', 'something:invented'],
    },
  ],
}));

function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('the role picker', () => {
  it('says what the selected role is for, not just its name', () => {
    render(<RolePicker value="operator" onChange={() => {}} />, {
      wrapper: Wrapper,
    });

    expect(screen.getByText(/Runs the fleet/)).toBeInTheDocument();
    expect(screen.getByText(/cannot invite users/)).toBeInTheDocument();
  });

  it('lists the permissions the role actually grants, in words', async () => {
    render(<RolePicker value="operator" onChange={() => {}} />, {
      wrapper: Wrapper,
    });

    // Rendered from the fetched scope list, so this cannot claim a permission
    // the backend does not grant.
    expect(
      await screen.findByText('Load, unload and register models'),
    ).toBeInTheDocument();
    expect(screen.getByText('Manage nodes')).toBeInTheDocument();
  });

  it('distinguishes the two roles that are easiest to confuse', async () => {
    const { rerender } = render(
      <RolePicker value="operator" onChange={() => {}} />,
      { wrapper: Wrapper },
    );
    await screen.findByText('Load, unload and register models');
    expect(
      screen.queryByText('Invite, edit and remove accounts'),
    ).not.toBeInTheDocument();

    rerender(<RolePicker value="tenant_admin" onChange={() => {}} />);

    await waitFor(() =>
      expect(
        screen.getByText('Invite, edit and remove accounts'),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText('Load, unload and register models'),
    ).not.toBeInTheDocument();
  });

  it('shows an unnamed scope by its identifier rather than dropping it', async () => {
    // Understating what a role grants is the one direction this screen must
    // not be wrong in, so a permission with no wording still appears.
    //
    // This asserted on `api_key:write_any` when first written, which
    // SCOPE_LABELS *does* name — so it passed without ever reaching the
    // `?? scope` fallback it claims to cover. A test that cannot fail is worse
    // than none, because it reads as coverage.
    render(<RolePicker value="tenant_admin" onChange={() => {}} />, {
      wrapper: Wrapper,
    });

    expect(await screen.findByText('something:invented')).toBeInTheDocument();
    // And the named ones are still rendered in words, not identifiers.
    expect(
      screen.getByText("Create and revoke anyone's API keys"),
    ).toBeInTheDocument();
    expect(screen.queryByText('api_key:write_any')).not.toBeInTheDocument();
  });
});
