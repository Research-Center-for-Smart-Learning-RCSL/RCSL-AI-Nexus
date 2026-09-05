import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { REDUCED_MOTION_QUERY, stubMatchMedia } from '@/test-support/match-media';
import { Menu, MenuContent, MenuItem, MenuTrigger } from './menu';

describe('MenuContent feedback', () => {
  afterEach(() => vi.restoreAllMocks());

  it('opens and activates its item without waiting for motion when reduced motion is requested', async () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: true });
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(
      <Menu>
        <MenuTrigger>Actions</MenuTrigger>
        <MenuContent>
          <MenuItem onClick={onAction}>Archive</MenuItem>
        </MenuContent>
      </Menu>,
    );

    await user.click(screen.getByRole('button', { name: 'Actions' }));
    const menu = await screen.findByRole('menu');
    expect(menu).toHaveClass('nexus-menu-popover');

    await user.click(screen.getByRole('menuitem', { name: 'Archive' }));
    expect(onAction).toHaveBeenCalledOnce();
  });
});
