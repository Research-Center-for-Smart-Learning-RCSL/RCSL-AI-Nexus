import { beforeEach, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import type { ReactNode } from 'react';

import { AppShell } from '@/components/composed/app-shell';
import { ROLE_SCOPES } from '@/lib/generated/role-scopes';
import type { ScopeName } from '@/lib/session';

/**
 * What the sidebar shows, and where an out-of-scope URL lands.
 *
 * This was the last piece of navigation with no test, and it is the one that
 * changed shape twice in a day: `adminOnly: true` was accurate while there were
 * two roles and wrong the moment there were six, and `Usage` moved from
 * `usage:read_all` to `usage:read_own` when the screen learned to serve both.
 * Neither change breaks anything a type checker can see. A link that should be
 * hidden and is not looks like a working screen until the request 403s, and a
 * link that should be visible and is not looks like a feature nobody built.
 *
 * The contract asserted here is the one the nav table's own comment states:
 * **a hidden link and a 403 mean the same thing.** So these tests drive on
 * scopes, not on role names — the authoritative role-to-scope table is the
 * backend's `role_authorization.py`, and duplicating it here would only assert
 * that a copy matches itself. The scope sets below are named after roles for
 * readability and are exercised for the filtering they produce.
 *
 * Not covered, deliberately: that each `requires` names the scope its screen's
 * first request actually needs. Only the backend can answer that, and it does,
 * in the use case that raises when the scope is absent.
 */

export const replace = vi.fn();
let pathname = '/dashboard';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
  usePathname: () => pathname,
}));

// The drawer opens its own connection to the assistant endpoint on mount, which
// is a different screen's contract; the shell only has to render it.
vi.mock('@/features/assistant/components/assistant-drawer', () => ({
  AssistantDrawer: () => null,
}));

vi.mock('@/features/assistant/context', () => ({
  AssistantContextProvider: ({ children }: { children: ReactNode }) => children,
  useAssistantContext: () => ({ isOpen: false, setOpen: vi.fn() }),
}));

const session = {
  me: {
    id: 'u1',
    auth_mode: 'local' as const,
    login: 'someone@example.test',
    display_name: 'Someone',
    role: 'user' as const,
    scopes: [] as ScopeName[] | undefined,
    session_expires_at: null,
  },
  status: 'authenticated' as const,
  authMode: 'local' as const,
  can: (scope: ScopeName) => (session.me.scopes ?? []).includes(scope),
  error: null,
  refresh: vi.fn(),
  signOut: vi.fn(),
};

vi.mock('@/lib/session', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/session')>();
  return {
    ...actual,
    useSession: () => session,
    useSessionExpiry: () => ({ msRemaining: null, shouldWarn: false }),
  };
});

/** Every scope the backend defines, so `admin` is expressed as "all of them". */
// The role map comes from the backend now, not from a copy kept here.
//
// This block used to be a hand-written transcription of
// `role_authorization.py`, and it disagreed with it twice on 2026-08-09:
// `prompt:read` reaches every human role and was listed for none, and after
// that was corrected the two role sets built from scratch rather than from
// `_BASE_SCOPES` — `auditor` and `curator` — were still missing entries. Each
// time the suite stayed green while describing a navigation nobody is shown.
//
// **The assertions below are unchanged in kind.** What a role *holds* is now
// followed rather than restated; what a role can *see* is still written out
// link by link, so a scope change that alters the navigation fails here with
// the expected list beside it. Generation removes the copy, not the check.
export const SCOPES: Record<string, readonly ScopeName[]> = ROLE_SCOPES;

export function signedInWith(scopes: readonly ScopeName[] | undefined, at = '/dashboard') {
  session.me.scopes = scopes ? [...scopes] : undefined;
  pathname = at;
}

export function sidebarLinks(): string[] {
  // Scope this to the navigation landmark: the sidebar also contains the home
  // logo link, which is shell chrome rather than a screen catalog entry.
  const aside = screen.getByRole('complementary');
  return within(within(aside).getByRole('navigation', { name: 'Screens' }))
    .getAllByRole('link')
    .map((a) => a.textContent?.trim() ?? '');
}

beforeEach(() => {
  replace.mockClear();
  window.localStorage.clear();
  // `user` is exactly `_BASE_SCOPES` on the backend, which is what this
  // default stood for when it was written by hand.
  signedInWith(SCOPES.user);
});

export function TestAppShell({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
