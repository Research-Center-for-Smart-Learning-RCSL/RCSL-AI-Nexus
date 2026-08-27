import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { Me, SessionStatus } from '@/lib/session';
import { LandingPage } from './landing-page';

const state: { me: Me | null; status: SessionStatus } = {
  me: null,
  status: 'loading',
};

vi.mock('@/lib/session', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/session')>();
  return {
    ...actual,
    useSession: () => state,
  };
});

vi.mock('next/image', () => ({
  default: ({ alt, priority: _priority, ...props }: React.ImgHTMLAttributes<HTMLImageElement> & { priority?: boolean }) => (
    // The image optimizer is not part of the landing page's session contract.
    // eslint-disable-next-line @next/next/no-img-element
    <img alt={alt} {...props} />
  ),
}));

beforeEach(() => {
  state.me = null;
  state.status = 'loading';
});

describe('the public landing page action', () => {
  it('holds a neutral action while session state is loading', () => {
    render(<LandingPage />);

    expect(screen.getByText('Checking your access…')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /sign in/i })).toBeNull();
    expect(screen.queryByRole('link', { name: /console/i })).toBeNull();
  });

  it('sends an anonymous visitor to sign in', () => {
    state.status = 'unauthenticated';
    render(<LandingPage />);

    expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute(
      'href',
      '/login',
    );
  });

  it('names the account and sends an authenticated visitor to the console', () => {
    state.status = 'authenticated';
    state.me = {
      id: 'u1',
      auth_mode: 'local',
      login: 'operator@example.test',
      display_name: 'Nexus Operator',
      role: 'operator',
      scopes: [],
      session_expires_at: null,
    };
    render(<LandingPage />);

    expect(screen.getByText('Nexus Operator')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to the console/i })).toHaveAttribute(
      'href',
      '/dashboard',
    );
  });
});
