import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { SCOPES, sidebarLinks, signedInWith, TestAppShell } from './app-shell-test-support';

describe('the collapsible groups', () => {
  it('offers no group a role has nothing in', () => {
    // An empty heading is worse than the flat list this replaced: it names a
    // capability the reader does not have and then offers nothing behind it.
    signedInWith(SCOPES.user);
    render(<TestAppShell>content</TestAppShell>);

    const aside = screen.getByRole('complementary');
    expect(within(aside).getByRole('button', { name: /Integration/ })).toBeInTheDocument();
    expect(within(aside).queryByRole('button', { name: /Fleet/ })).toBeNull();
    expect(within(aside).queryByRole('button', { name: /Administration/ })).toBeNull();
  });

  it('folds a group away and remembers it', async () => {
    const user = userEvent.setup();
    signedInWith(SCOPES.admin, '/chat');
    render(<TestAppShell>content</TestAppShell>);

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
    render(<TestAppShell>content</TestAppShell>);

    await user.click(screen.getByRole('button', { name: /Fleet/ }));

    expect(sidebarLinks()).toContain('Models');
    expect(JSON.parse(window.localStorage.getItem('nexus.nav.collapsed') ?? '[]')).toContain(
      'fleet',
    );
  });

  it('starts from what was folded last time', () => {
    window.localStorage.setItem('nexus.nav.collapsed', JSON.stringify(['administration']));
    signedInWith(SCOPES.admin, '/chat');
    render(<TestAppShell>content</TestAppShell>);

    expect(sidebarLinks()).not.toContain('Users');
    expect(sidebarLinks()).toContain('Models');
  });

  it('ignores a stored value it cannot use rather than failing to render', () => {
    // A UI preference. The cost of a bad value is one lost fold, and code that
    // rehabilitates malformed JSON is code nobody can justify.
    window.localStorage.setItem('nexus.nav.collapsed', '{not json');
    signedInWith(SCOPES.admin, '/chat');
    render(<TestAppShell>content</TestAppShell>);

    expect(sidebarLinks()).toContain('Users');
  });
});

describe('the pinned entry', () => {
  it('sits above every group heading', () => {
    signedInWith(SCOPES.admin, '/chat');
    render(<TestAppShell>content</TestAppShell>);

    expect(sidebarLinks()[0]).toBe('Chat');
  });

  it('belongs to no group, so no fold can reach it', async () => {
    // The failure this prevents: Chat hidden by a preference set weeks earlier,
    // on the one screen where "I could not find it" is the whole failure — and
    // the screen an out-of-scope URL redirects to.
    const user = userEvent.setup();
    signedInWith(SCOPES.admin, '/usage');
    render(<TestAppShell>content</TestAppShell>);

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
    render(<TestAppShell>content</TestAppShell>);

    expect(sidebarLinks()).toEqual([
      'Chat',
      'API keys',
      'API reference',
      'Connect an agent',
    ]);
  });
});
