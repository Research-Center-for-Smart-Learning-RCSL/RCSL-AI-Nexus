import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

import { AppShell } from '@/components/composed/app-shell';
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

const replace = vi.fn();
let pathname = '/';

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
const ALL: ScopeName[] = [
  'chat:use',
  'model:read',
  'model:write',
  'routing:read',
  'routing:write',
  'api_key:read_own',
  'api_key:write_own',
  'api_key:write_any',
  'user:read',
  'user:write',
  'node:read',
  'node:write',
  'tenant:read',
  'tenant:write',
  'usage:read_own',
  'usage:read_all',
  'logs:read',
  'knowledge:read',
  'knowledge:write',
  'retention:write',
];

const BASE: ScopeName[] = [
  'chat:use',
  'api_key:read_own',
  'api_key:write_own',
  'usage:read_own',
];

const SCOPES: Record<string, ScopeName[]> = {
  admin: ALL,
  operator: [
    ...BASE,
    'model:read',
    'model:write',
    'node:read',
    'node:write',
    'routing:read',
    'routing:write',
    'logs:read',
    'usage:read_all',
    'knowledge:read',
    'user:read',
    'tenant:read',
  ],
  curator: [...BASE, 'knowledge:read', 'knowledge:write'],
  auditor: [
    'chat:use',
    'api_key:read_own',
    'usage:read_own',
    'usage:read_all',
    'logs:read',
    'model:read',
    'routing:read',
    'node:read',
    'user:read',
    'tenant:read',
    'knowledge:read',
  ],
  user: BASE,
};

function signedInWith(scopes: ScopeName[] | undefined, at = '/') {
  session.me.scopes = scopes;
  pathname = at;
}

function sidebarLinks(): string[] {
  // The sidebar is the `complementary` landmark; the narrow-screen panel is a
  // dialog and is asserted separately, so this cannot accidentally read both.
  const aside = screen.getByRole('complementary');
  return within(aside)
    .getAllByRole('link')
    .map((a) => a.textContent?.trim() ?? '');
}

beforeEach(() => {
  replace.mockClear();
  window.localStorage.clear();
  signedInWith(BASE);
});

describe('the links a role can see', () => {
  it('shows an admin everything', () => {
    signedInWith(SCOPES.admin);
    render(<AppShell>content</AppShell>);

    // Grouped order: Work, Fleet, Insight, Administration.
    expect(sidebarLinks()).toEqual([
      'Chat',
      'API keys',
      'API',
      'Models',
      'Routing',
      'Nodes',
      'Knowledge',
      'Dashboard',
      'Usage',
      'Logs',
      'Users',
      'Tenants',
      'Retention',
    ]);
  });

  it('shows a plain member only what an account by itself is worth', () => {
    // The set `_BASE_SCOPES` grants, and the reason `Usage` is in this list:
    // before 2026-08-04 it required `usage:read_all` and a member could not
    // reach their own figures from anywhere in the UI.
    signedInWith(SCOPES.user);
    render(<AppShell>content</AppShell>);

    expect(sidebarLinks()).toEqual(['Chat', 'API keys', 'API', 'Usage']);
  });

  it('shows an operator the fleet and withholds the screens that grant things', () => {
    signedInWith(SCOPES.operator);
    render(<AppShell>content</AppShell>);

    const links = sidebarLinks();
    expect(links).toContain('Models');
    expect(links).toContain('Nodes');
    expect(links).toContain('Routing');
    // Present, because diagnosing load means knowing whose it is. Both read-only
    // server-side; the screens hide their own write controls.
    expect(links).toContain('Users');
    expect(links).toContain('Tenants');
  });

  it('shows a curator the knowledge base and nothing else administrative', () => {
    signedInWith(SCOPES.curator);
    render(<AppShell>content</AppShell>);

    expect(sidebarLinks()).toEqual([
      'Chat',
      'API keys',
      'API',
      'Knowledge',
      'Usage',
    ]);
  });

  it('shows an auditor every screen but the one that deletes', () => {
    // Worth pinning because it looks like a mistake. An auditor holds a read
    // scope for everything, so the nav is nearly indistinguishable from an
    // admin's; what differs is inside each screen, where the write controls are
    // gated on the write scopes the role does not have. The exception is
    // Retention, which is admin-only — a role that writes nothing must not be
    // able to delete everything.
    signedInWith(SCOPES.auditor);
    render(<AppShell>content</AppShell>);

    expect(sidebarLinks()).toHaveLength(12);
    expect(sidebarLinks()).not.toContain('Retention');
  });

  it('gives the narrow-screen panel the same links as the sidebar', async () => {
    // One definition serves both, and this is the assertion that keeps it that
    // way: a second copy of the nav is a copy that falls behind on the next
    // scope change, and the one that falls behind is the one nobody looks at.
    signedInWith(SCOPES.operator);
    render(<AppShell>content</AppShell>);

    const fromSidebar = sidebarLinks();
    await userEvent.click(screen.getByRole('button', { name: 'Open the menu' }));
    const panel = screen.getByRole('dialog', { name: 'Navigation' });

    expect(
      within(panel)
        .getAllByRole('link')
        .map((a) => a.textContent?.trim() ?? ''),
    ).toEqual(fromSidebar);
  });
});

// The nav renders whatever `can` answers, so what `can` answers when the server
// reports no scopes at all belongs with `can` itself: see lib/session.test.tsx.

describe('a URL the account has no scope for', () => {
  it('is redirected to the one screen everybody can use', () => {
    // The nav hides the link; this covers the address bar, a bookmark, and a
    // link pasted by somebody with more scopes than the reader.
    signedInWith(SCOPES.user, '/users');
    render(<AppShell>content</AppShell>);

    expect(replace).toHaveBeenCalledWith('/chat');
  });

  it('leaves a permitted screen alone', () => {
    signedInWith(SCOPES.user, '/usage');
    render(<AppShell>content</AppShell>);

    expect(replace).not.toHaveBeenCalled();
  });

  it('sends a member off the dashboard, which is the index everyone opens', () => {
    // `/` requires `usage:read_all`, so for a member the landing page is one
    // they cannot read. Without the guard they would arrive on a 403 rather
    // than anywhere useful.
    signedInWith(SCOPES.user, '/');
    render(<AppShell>content</AppShell>);

    expect(replace).toHaveBeenCalledWith('/chat');
  });

  it('leaves the dashboard alone for someone who can read it', () => {
    signedInWith(SCOPES.operator, '/');
    render(<AppShell>content</AppShell>);

    expect(replace).not.toHaveBeenCalled();
  });
});

describe('the collapsible groups', () => {
  it('offers no group a role has nothing in', () => {
    // An empty heading is worse than the flat list this replaced: it names a
    // capability the reader does not have and then offers nothing behind it.
    signedInWith(SCOPES.user);
    render(<AppShell>content</AppShell>);

    const aside = screen.getByRole('complementary');
    expect(within(aside).getByRole('button', { name: /Work/ })).toBeInTheDocument();
    expect(within(aside).queryByRole('button', { name: /Fleet/ })).toBeNull();
    expect(within(aside).queryByRole('button', { name: /Administration/ })).toBeNull();
  });

  it('folds a group away and remembers it', async () => {
    const user = userEvent.setup();
    signedInWith(SCOPES.admin, '/chat');
    render(<AppShell>content</AppShell>);

    expect(sidebarLinks()).toContain('Models');
    await user.click(screen.getByRole('button', { name: /Fleet/ }));

    expect(sidebarLinks()).not.toContain('Models');
    expect(screen.getByRole('button', { name: /Fleet/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(JSON.parse(window.localStorage.getItem('nexus.nav.collapsed') ?? '[]')).toContain(
      'fleet',
    );
  });

  it('will not fold away the group holding the current page', async () => {
    // Otherwise the reader collapses Fleet while standing on Models, the
    // highlighted item disappears, and the sidebar stops saying where they are
    // — the one thing it is for. The fold is still recorded and takes effect
    // once they navigate elsewhere.
    const user = userEvent.setup();
    signedInWith(SCOPES.admin, '/models');
    render(<AppShell>content</AppShell>);

    await user.click(screen.getByRole('button', { name: /Fleet/ }));

    expect(sidebarLinks()).toContain('Models');
    expect(JSON.parse(window.localStorage.getItem('nexus.nav.collapsed') ?? '[]')).toContain(
      'fleet',
    );
  });

  it('starts from what was folded last time', () => {
    window.localStorage.setItem('nexus.nav.collapsed', JSON.stringify(['administration']));
    signedInWith(SCOPES.admin, '/chat');
    render(<AppShell>content</AppShell>);

    expect(sidebarLinks()).not.toContain('Users');
    expect(sidebarLinks()).toContain('Models');
  });

  it('ignores a stored value it cannot use rather than failing to render', () => {
    // A UI preference. The cost of a bad value is one lost fold, and code that
    // rehabilitates malformed JSON is code nobody can justify.
    window.localStorage.setItem('nexus.nav.collapsed', '{not json');
    signedInWith(SCOPES.admin, '/chat');
    render(<AppShell>content</AppShell>);

    expect(sidebarLinks()).toContain('Users');
  });
});
