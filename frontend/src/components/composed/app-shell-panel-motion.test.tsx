import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PANEL_MOTION_MS } from '@/lib/panel-motion';
import { REDUCED_MOTION_QUERY, stubMatchMedia } from '@/test-support/match-media';

import { SCOPES, signedInWith, TestAppShell } from './app-shell-test-support';

function openMenu() {
  const menuButton = screen.getByRole('button', { name: 'Open the menu' });
  fireEvent.click(menuButton);
  return { menuButton, panel: screen.getByRole('dialog', { name: 'Navigation' }) };
}

describe('mobile navigation panel motion', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    signedInWith(SCOPES.user, '/chat');
  });

  afterEach(() => vi.useRealTimers());

  it('renders its exit, makes it inert immediately, and restores focus afterward', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: false });
    render(<TestAppShell>content</TestAppShell>);
    const { menuButton, panel } = openMenu();

    expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    expect(panel).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Close the menu' }));

    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveAttribute('data-panel-state', 'closed');
    expect(panel).toHaveAttribute('aria-hidden', 'true');
    expect(panel).toHaveAttribute('inert');
    expect(menuButton).not.toHaveFocus();

    act(() => vi.advanceTimersByTime(PANEL_MOTION_MS));
    expect(screen.queryByRole('dialog', { name: 'Navigation' })).toBeNull();
    expect(menuButton).toHaveFocus();
  });

  it('keeps Escape dismissal and aria-expanded while an exit is pending', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: false });
    render(<TestAppShell>content</TestAppShell>);
    const { menuButton, panel } = openMenu();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    expect(panel).toHaveAttribute('inert');
    act(() => vi.advanceTimersByTime(PANEL_MOTION_MS));
    expect(menuButton).toHaveFocus();
  });

  it('does not wait for an animation interval under reduced motion', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: true });
    render(<TestAppShell>content</TestAppShell>);
    const { menuButton } = openMenu();

    fireEvent.click(screen.getByRole('button', { name: 'Close the menu' }));
    expect(screen.queryByRole('dialog', { name: 'Navigation' })).toBeNull();
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    expect(menuButton).toHaveFocus();
  });
});
