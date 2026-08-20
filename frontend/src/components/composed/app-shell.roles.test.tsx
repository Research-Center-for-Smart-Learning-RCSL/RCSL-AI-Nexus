import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { SCOPES, sidebarLinks, signedInWith, TestAppShell } from './app-shell-test-support';

describe('the links a role can see', () => {
  it('shows an admin everything', () => {
    signedInWith(SCOPES.admin);
    render(<TestAppShell>content</TestAppShell>);

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
      'Audit log',
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
    render(<TestAppShell>content</TestAppShell>);

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
    render(<TestAppShell>content</TestAppShell>);

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
    render(<TestAppShell>content</TestAppShell>);

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
    render(<TestAppShell>content</TestAppShell>);

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
    render(<TestAppShell>content</TestAppShell>);

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
