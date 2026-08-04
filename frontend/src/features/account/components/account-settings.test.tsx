import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { AccountSettings } from '@/features/account/components/account-settings';

/**
 * The account screen showed a role name and nothing else, so "why can I not
 * see the Logs screen" had no answer anywhere a non-administrator could reach.
 * It now lists the scopes `GET /admin/me` reported — what the request was
 * actually authorized with, rather than a description of the role's name.
 */

const session = vi.fn();
vi.mock('@/lib/session', () => ({
  useSession: () => session(),
}));

// Rendered only on the public entrance, and irrelevant here.
vi.mock('@/features/account/components/change-password-form', () => ({
  ChangePasswordForm: () => null,
}));
vi.mock('@/features/account/components/totp-reenrolment-card', () => ({
  TotpReenrolmentCard: () => null,
}));

function signedInAs(role: string, scopes: string[] | undefined) {
  session.mockReturnValue({
    me: {
      id: 'u-1',
      login: 'someone@ntnu.edu.tw',
      display_name: 'Someone',
      role,
      scopes,
      auth_mode: 'tailnet',
      session_expires_at: null,
    },
    status: 'authenticated',
    // `tailnet` so the password and TOTP cards stay out of the way; this
    // screen's permissions card is the same on both entrances.
    authMode: 'tailnet',
    can: () => false,
    isAdmin: false,
    hasSession: false,
    error: null,
    refresh: vi.fn(),
    signOut: vi.fn(),
  });
}

beforeEach(() => session.mockReset());

describe('the account screen', () => {
  it('names the role in words rather than showing the stored value', () => {
    signedInAs('tenant_admin', ['chat:use']);
    render(<AccountSettings />);

    expect(screen.getByText(/Tenant administrator/)).toBeInTheDocument();
    expect(screen.queryByText(/tenant_admin/)).not.toBeInTheDocument();
  });

  it('lists what the account may actually do, in words', () => {
    signedInAs('operator', ['model:write', 'node:write', 'logs:read']);
    render(<AccountSettings />);

    expect(
      screen.getByText('Load, unload and register models'),
    ).toBeInTheDocument();
    expect(screen.getByText('Read the audit log')).toBeInTheDocument();
    expect(screen.getByText(/3 permissions/)).toBeInTheDocument();
  });

  it('shows an unnamed scope by its identifier rather than dropping it', () => {
    signedInAs('operator', ['something:invented']);
    render(<AccountSettings />);

    // Understating what is granted is the one direction this must not be
    // wrong in, so an unrecognised permission still appears.
    expect(screen.getByText('something:invented')).toBeInTheDocument();
  });

  it('separates "reported none" from "did not report"', () => {
    signedInAs('user', undefined);
    render(<AccountSettings />);

    // The two are the same empty list and mean opposite things: one is an
    // account with no permissions, the other a server that did not say.
    expect(screen.getByText(/did not report your permissions/)).toBeInTheDocument();
    expect(screen.queryByText(/0 permissions/)).not.toBeInTheDocument();
  });
});
