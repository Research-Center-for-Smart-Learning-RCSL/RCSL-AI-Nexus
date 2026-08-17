import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
const SCOPES: Record<string, readonly ScopeName[]> = ROLE_SCOPES;

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
  // `user` is exactly `_BASE_SCOPES` on the backend, which is what this
  // default stood for when it was written by hand.
  signedInWith(SCOPES.user);
});

describe('the links a role can see', () => {
  it('shows an admin everything', () => {
    signedInWith(SCOPES.admin);
    render(<AppShell>content</AppShell>);

    // Chat is pinned above every group; then Integration, Fleet, Evidence,
    // Content, Insight, Administration.
    expect(sidebarLinks()).toEqual([
      'Chat',
      'API keys',
      'API reference',
      'Connect an agent',
      'Models',
      'Routing policies',
      'Nodes',
      'Model evaluation',
      'Prompt templates',
      'Knowledge',
      'Dashboard',
      'Usage',
      'Logs',
      'Transcripts',
      'Refusals',
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

    // `Prompt templates` is the whole of what a member sees under Content, and
    // the reason that group is not called Fleet: they hold none of
    // `model:read`, `routing:read` or `node:read`, so a Fleet group would have
    // shown them one content entry under an infrastructure heading. The same
    // scope is why no Evidence group appears here: a group whose every entry is
    // filtered out is not rendered at all.
    expect(sidebarLinks()).toEqual([
      'Chat',
      'API keys',
      'API reference',
      'Connect an agent',
      'Prompt templates',
      'Usage',
      'Refusals',
    ]);
  });

  it('shows an operator the fleet and withholds the screens that grant things', () => {
    signedInWith(SCOPES.operator);
    render(<AppShell>content</AppShell>);

    const links = sidebarLinks();
    expect(links).toContain('Models');
    expect(links).toContain('Nodes');
    expect(links).toContain('Routing policies');
    // Present, because diagnosing load means knowing whose it is. Both read-only
    // server-side; the screens hide their own write controls.
    expect(links).toContain('Users');
    expect(links).toContain('Tenants');
  });

  it('shows a curator the knowledge base and nothing else administrative', () => {
    signedInWith(SCOPES.curator);
    render(<AppShell>content</AppShell>);

    // Both Content entries and no Fleet entry, which is the role's definition
    // rendered: `_CURATOR_SCOPES` is "what the models are told, and nothing
    // else".
    expect(sidebarLinks()).toEqual([
      'Chat',
      'API keys',
      'API reference',
      'Connect an agent',
      'Prompt templates',
      'Knowledge',
      'Usage',
      'Refusals',
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

    // 14 since 2026-08-09: Prompt templates, which an auditor has always been
    // able to open and which this file's scope map did not know they held. 15
    // since 2026-08-17: Model evaluation, which is gated on `model:read` and
    // therefore reaches this role — an auditor reading the evidence behind a
    // routing decision is the role working as intended.
    expect(sidebarLinks()).toHaveLength(16);
    expect(sidebarLinks()).toContain('Model evaluation');
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

  it('does not render the screen it is redirecting away from', () => {
    // The redirect is an effect, so it cannot pre-empt the mount; only not
    // rendering the children can. What mounts sends its queries, and each
    // refusal is an `authz.denied` audit row — so before this, every sign-in
    // by a member wrote two, for scopes they were never shown a link to.
    signedInWith(SCOPES.user, '/');
    render(<AppShell>content</AppShell>);

    expect(replace).toHaveBeenCalledWith('/chat');
    expect(screen.queryByText('content')).not.toBeInTheDocument();
  });

  it('still renders a permitted screen', () => {
    signedInWith(SCOPES.user, '/usage');
    render(<AppShell>content</AppShell>);

    expect(screen.getByText('content')).toBeInTheDocument();
  });
});

describe('the collapsible groups', () => {
  it('offers no group a role has nothing in', () => {
    // An empty heading is worse than the flat list this replaced: it names a
    // capability the reader does not have and then offers nothing behind it.
    signedInWith(SCOPES.user);
    render(<AppShell>content</AppShell>);

    const aside = screen.getByRole('complementary');
    expect(within(aside).getByRole('button', { name: /Integration/ })).toBeInTheDocument();
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

describe('the pinned entry', () => {
  it('sits above every group heading', () => {
    signedInWith(SCOPES.admin, '/chat');
    render(<AppShell>content</AppShell>);

    expect(sidebarLinks()[0]).toBe('Chat');
  });

  it('belongs to no group, so no fold can reach it', async () => {
    // The failure this prevents: Chat hidden by a preference set weeks earlier,
    // on the one screen where "I could not find it" is the whole failure — and
    // the screen an out-of-scope URL redirects to.
    const user = userEvent.setup();
    signedInWith(SCOPES.admin, '/usage');
    render(<AppShell>content</AppShell>);

    for (const group of [/Integration/, /Fleet/, /Insight/, /Administration/]) {
      const header = screen.queryByRole('button', { name: group });
      if (header) await user.click(header);
    }

    expect(sidebarLinks()).toContain('Chat');
  });

  it('declares no scope, which is why an empty account still sees it', () => {
    // Every role holds `chat:use`, so Chat asks for nothing and this is what an
    // account with no scopes at all is left with. The filter that would hide a
    // pinned entry exists in the code and nothing exercises it today, because
    // nothing pinned declares a scope — pinned and permitted are separate
    // properties, and the first pinned item that needs one is where that
    // matters.
    signedInWith([]);
    render(<AppShell>content</AppShell>);

    expect(sidebarLinks()).toEqual([
      'Chat',
      'API keys',
      'API reference',
      'Connect an agent',
    ]);
  });
});
