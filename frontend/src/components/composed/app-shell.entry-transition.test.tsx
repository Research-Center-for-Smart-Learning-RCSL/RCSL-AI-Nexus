import { act, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { REDUCED_MOTION_QUERY, stubMatchMedia } from '@/test-support/match-media';
import type { ScopeName } from '@/lib/session';

/**
 * The join between the shell and the curtain, which no other suite can see:
 * `app-shell-test-support.tsx` mocks `AppEntryTransition` away so the
 * navigation tests observe a settled shell, and `entry-transition.test.tsx`
 * drives the curtain with no shell around it.
 *
 * What is asserted here is a **positional contract**. `AppShell` renders the
 * curtain from two different branches — beside the loading gate, then beside
 * the authenticated shell — and only React's index-wise reconciliation of the
 * fragment keeps that from being two component instances. If it ever becomes
 * two, the curtain restarts its timeline the moment the session settles, which
 * is the opposite of the minimum-duration hold it exists to provide, and every
 * unit test of both halves still passes.
 */

const router = { replace: vi.fn() };
vi.mock('next/navigation', () => ({
  useRouter: () => router,
  usePathname: () => '/dashboard',
}));

vi.mock('@/features/assistant/components/assistant-drawer', () => ({
  AssistantDrawer: () => null,
}));

vi.mock('@/features/assistant/context', () => ({
  AssistantContextProvider: ({ children }: { children: ReactNode }) => children,
  useAssistantContext: () => ({ isOpen: false, setOpen: vi.fn() }),
}));

vi.mock('next-themes', () => ({ useTheme: () => ({ resolvedTheme: 'dark' }) }));

// The curtain is the subject; the GPU behind it is not, and jsdom has none.
vi.mock('./entry-transition-scenes', () => ({
  EntryScene: () => null,
  LandingScene: () => null,
}));

const session = {
  me: null as unknown,
  status: 'loading' as 'loading' | 'authenticated',
  authMode: 'local' as const,
  can: () => true,
  isAdmin: true,
  hasSession: false,
  error: null,
  refresh: vi.fn(),
  signOut: vi.fn(),
};

const ME = {
  id: 'u1',
  auth_mode: 'local' as const,
  login: 'someone@example.test',
  display_name: 'Someone',
  role: 'admin' as const,
  scopes: undefined as ScopeName[] | undefined,
  session_expires_at: null,
};

vi.mock('@/lib/session', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/session')>();
  return {
    ...actual,
    useSession: () => session,
    useSessionExpiry: () => ({ msRemaining: null, shouldWarn: false }),
  };
});

const { AppShell } = await import('./app-shell-runtime');

function settle() {
  session.status = 'authenticated';
  session.me = ME;
}

beforeEach(() => {
  vi.useFakeTimers();
  stubMatchMedia({ [REDUCED_MOTION_QUERY]: false });
  session.status = 'loading';
  session.me = null;
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe('the entry curtain across the session gate', () => {
  it('is the same mounted curtain before and after the identity settles', () => {
    const view = render(<AppShell>content</AppShell>);
    const whileLoading = screen.getByTestId('entry-curtain-layers');

    act(() => vi.advanceTimersByTime(800));
    settle();
    view.rerender(<AppShell>content</AppShell>);

    // Node identity, not merely presence: a remount would also find *a*
    // curtain here, having thrown away the 800ms already served.
    expect(screen.getByTestId('entry-curtain-layers')).toBe(whileLoading);
    expect(screen.getByText('content')).toBeInTheDocument();
  });

  it('lets the settled shell finish the hold rather than starting a new one', () => {
    const view = render(<AppShell>content</AppShell>);

    // Past the 1600ms timeline while the session is still loading: the curtain
    // may not leave, because `canFinish` is false until the shell says settled.
    act(() => vi.advanceTimersByTime(1600));
    expect(screen.getByTestId('entry-curtain-layers')).toBeInTheDocument();

    settle();
    view.rerender(<AppShell>content</AppShell>);
    // Only the 220ms exit remains. A restarted instance would need 1600 more.
    act(() => vi.advanceTimersByTime(400));
    expect(screen.queryByTestId('entry-curtain-layers')).toBeNull();
  });

  it('gives the viewer the shell back even if the identity never settles', () => {
    render(<AppShell>content</AppShell>);
    expect(screen.getByTestId('entry-curtain-layers')).toBeInTheDocument();

    // The watchdog's ceiling for a 1600ms timeline. Nothing here reports a
    // frame, a timeline or a failure — the case the watchdog exists for.
    act(() => vi.advanceTimersByTime(3400));
    expect(screen.queryByTestId('entry-curtain-layers')).toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent('Checking your access');
  });
});
