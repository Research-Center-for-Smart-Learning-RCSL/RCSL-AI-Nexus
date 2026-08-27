import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { AuthMode, Me, SessionStatus } from '@/lib/session';
import { LandingPage } from './landing-page';

const state: {
  me: Me | null;
  status: SessionStatus;
  authMode: AuthMode | null;
  error: Error | null;
  refresh: () => Promise<void>;
} = {
  me: null,
  status: 'loading',
  authMode: null,
  error: null,
  refresh: () => Promise.resolve(),
};

vi.mock('@/lib/session', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/session')>();
  return {
    ...actual,
    useSession: () => state,
  };
});

vi.mock('next/image', () => ({
  default: (properties: React.ImgHTMLAttributes<HTMLImageElement> & { priority?: boolean }) => {
    const imageProperties = { ...properties };
    const alt = imageProperties.alt ?? '';
    delete imageProperties.priority;
    delete imageProperties.alt;
    return (
      // The image optimizer is not part of the landing page's session contract.
      // eslint-disable-next-line @next/next/no-img-element
      <img alt={alt} {...imageProperties} />
    );
  },
}));

beforeEach(() => {
  state.me = null;
  state.status = 'loading';
  state.authMode = null;
  state.error = null;
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

  it('keeps the API-error diagnosis instead of a dead-end sign-in link', () => {
    state.status = 'error';
    state.error = new Error('fetch failed');
    render(<LandingPage />);

    expect(screen.getByText('Could not reach the admin API')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    // /login asks the same unreachable API for a login; do not offer it.
    expect(screen.queryByRole('link', { name: /sign in/i })).toBeNull();
  });

  it('keeps the lost-tailnet diagnosis instead of a password login it cannot use', () => {
    state.status = 'unauthenticated';
    state.authMode = 'tailnet';
    render(<LandingPage />);

    expect(screen.getByText('Tailscale connection lost')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /sign in/i })).toBeNull();
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
