import { createRef } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AppShellHeader } from '@/components/composed/app-shell-header';
import type { AuthMode, Me } from '@/lib/session';

const theme = vi.hoisted(() => ({
  current: 'system',
  set: vi.fn(),
}));

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: theme.current, setTheme: theme.set }),
}));

const me: Me = {
  id: 'u1',
  auth_mode: 'local',
  login: 'someone@example.test',
  display_name: 'Someone',
  role: 'user',
  scopes: [],
  session_expires_at: null,
};

function renderHeader(authMode: AuthMode = 'local', meOverrides: Partial<Me> = {}) {
  const signOut = vi.fn(async () => undefined);
  const setAssistantOpen = vi.fn();

  render(
    <AppShellHeader
      navButtonRef={createRef<HTMLButtonElement>()}
      navOpen={false}
      setNavOpen={vi.fn()}
      me={{ ...me, auth_mode: authMode, ...meOverrides }}
      authMode={authMode}
      assistant={{ isOpen: false, setOpen: setAssistantOpen }}
      signOut={signOut}
    />,
  );

  return { setAssistantOpen, signOut };
}

describe('the responsive app header', () => {
  beforeEach(() => {
    theme.current = 'system';
    theme.set.mockClear();
  });

  it('uses one account and appearance menu at every breakpoint', async () => {
    const user = userEvent.setup();
    renderHeader();

    const trigger = screen.getByRole('button', {
      name: 'Open account and appearance menu',
    });
    expect(trigger).not.toHaveClass('md:hidden');
    expect(within(trigger).getByText('Someone').parentElement).toHaveClass(
      'hidden',
      'md:block',
    );
    expect(screen.queryByRole('link', { name: 'Account' })).not.toBeInTheDocument();

    await user.click(trigger);
    const menu = await screen.findByRole('menu');

    expect(within(menu).getByText('Someone')).toBeVisible();
    expect(within(menu).getByText(/someone@example\.test/)).toHaveTextContent(
      'someone@example.test – User',
    );
    expect(
      within(menu).getByRole('menuitem', { name: 'Account settings' }),
    ).toHaveAttribute('href', '/account');

    await user.click(
      within(menu).getByRole('menuitem', {
        name: 'Theme: System. Switch to light.',
      }),
    );
    expect(theme.set).toHaveBeenCalledWith('light');
  });

  it('wraps a complete long identity inside the menu', async () => {
    const user = userEvent.setup();
    const displayName = 'Someone With A Deliberately Long Display Name '.repeat(2).trim();
    const login = 'someone.with.a.deliberately.long.login@example.test';
    renderHeader('local', { display_name: displayName, login });

    await user.click(
      screen.getByRole('button', {
        name: 'Open account and appearance menu',
      }),
    );
    const menu = await screen.findByRole('menu');
    const fullName = within(menu).getByText(displayName);
    const fullLogin = within(menu).getByText(`${login} – User`);

    expect(menu).toHaveClass('w-80');
    expect(fullName).not.toHaveClass('truncate');
    expect(fullName).toHaveClass('[overflow-wrap:anywhere]');
    expect(fullLogin).not.toHaveClass('truncate');
    expect(fullLogin).toHaveTextContent(`${login} – User`);
  });

  it('supports arrow-key navigation and runs sign out from the menu', async () => {
    const user = userEvent.setup();
    const { signOut } = renderHeader();
    const trigger = screen.getByRole('button', {
      name: 'Open account and appearance menu',
    });

    trigger.focus();
    await user.keyboard('{Enter}');

    const menu = screen.getByRole('menu');
    const themeItem = within(menu).getByRole('menuitem', {
      name: 'Theme: System. Switch to light.',
    });
    const accountItem = within(menu).getByRole('menuitem', {
      name: 'Account settings',
    });
    const signOutItem = within(menu).getByRole('menuitem', {
      name: 'Sign out',
    });

    expect(themeItem).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(accountItem).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(signOutItem).toHaveFocus();
    await user.keyboard('{Enter}');

    expect(signOut).toHaveBeenCalledOnce();
  });

  it.each<AuthMode>(['tailnet', 'dev'])(
    'keeps local-account actions out of %s mode',
    async (authMode) => {
      const user = userEvent.setup();
      renderHeader(authMode);

      await user.click(
        screen.getByRole('button', {
          name: 'Open account and appearance menu',
        }),
      );
      const menu = await screen.findByRole('menu');

      expect(
        within(menu).getByRole('menuitem', {
          name: 'Theme: System. Switch to light.',
        }),
      ).toBeVisible();
      expect(
        within(menu).queryByRole('menuitem', { name: 'Account settings' }),
      ).not.toBeInTheDocument();
      expect(
        within(menu).queryByRole('menuitem', { name: 'Sign out' }),
      ).not.toBeInTheDocument();
    },
  );
});
