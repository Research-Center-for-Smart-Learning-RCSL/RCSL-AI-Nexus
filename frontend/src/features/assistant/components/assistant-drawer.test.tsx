import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PANEL_MOTION_MS } from '@/lib/panel-motion';
import { REDUCED_MOTION_QUERY, stubMatchMedia } from '@/test-support/match-media';

const assistantContext = vi.hoisted(() => ({
  isOpen: true,
  setOpen: vi.fn(),
  surface: 'other',
  canApply: false,
  applyPatch: vi.fn(),
}));

vi.mock('@/features/assistant/context', () => ({
  useAssistantContext: () => assistantContext,
}));

vi.mock('@/features/assistant/hooks/use-assistant', () => ({
  useAssistant: () => ({
    turns: [],
    isStreaming: false,
    store: {},
    send: vi.fn(),
    cancel: vi.fn(),
    clear: vi.fn(),
  }),
}));

vi.mock('@/lib/use-stick-to-bottom', () => ({
  useStickToBottom: () => ({
    containerRef: { current: null },
    contentRef: { current: null },
    onScroll: vi.fn(),
    pinned: true,
    scrollToBottom: vi.fn(),
  }),
}));

vi.mock('./assistant-composer', () => ({
  AssistantComposer: () => <div data-testid="assistant-composer" />,
}));

vi.mock('./assistant-turn', () => ({ AssistantTurn: () => null }));

import { AssistantDrawer } from './assistant-drawer';

function drawer() {
  return screen.getByRole('complementary', { name: 'Management assistant' });
}

describe('assistant drawer motion', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    assistantContext.isOpen = true;
    assistantContext.setOpen.mockReset();
    window.localStorage.clear();
  });

  afterEach(() => vi.useRealTimers());

  it('uses the shared inline-end motion while retaining its exit only for the visual interval', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: false });
    const view = render(<AssistantDrawer />);
    act(() => vi.runOnlyPendingTimers());
    const panel = drawer();

    expect(panel).toHaveClass('nexus-panel-from-inline-end', 'nexus-panel-motion');
    expect(panel).toHaveAttribute('data-panel-state', 'open');
    expect(panel).toHaveClass('fixed', 'w-full', 'max-w-none', 'lg:max-w-sm');
    expect(panel).not.toHaveAttribute('aria-modal');

    assistantContext.isOpen = false;
    view.rerender(<AssistantDrawer />);
    expect(panel).toHaveAttribute('data-panel-state', 'closed');
    expect(panel).toHaveAttribute('aria-hidden', 'true');
    expect(panel).toHaveAttribute('inert');

    panel.dispatchEvent(new Event('transitionend'));
    expect(panel).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(PANEL_MOTION_MS));
    expect(screen.queryByRole('complementary', { name: 'Management assistant' })).toBeNull();
  });

  it('does not wait to unmount under reduced motion', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: true });
    const view = render(<AssistantDrawer />);
    assistantContext.isOpen = false;
    view.rerender(<AssistantDrawer />);

    expect(screen.queryByRole('complementary', { name: 'Management assistant' })).toBeNull();
  });

  it('preserves the stored width choice as the drawer is widened and reopened', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: false });
    const view = render(<AssistantDrawer />);
    act(() => vi.runOnlyPendingTimers());

    fireEvent.click(screen.getByRole('button', { name: 'Widen the assistant' }));
    expect(window.localStorage.getItem('nexus.assistant.width')).toBe('wide');
    expect(drawer()).toHaveClass('max-w-none', 'lg:max-w-2xl');

    assistantContext.isOpen = false;
    view.rerender(<AssistantDrawer />);
    act(() => vi.advanceTimersByTime(PANEL_MOTION_MS));
    assistantContext.isOpen = true;
    view.rerender(<AssistantDrawer />);
    act(() => vi.runOnlyPendingTimers());

    expect(drawer()).toHaveClass('max-w-none', 'lg:max-w-2xl');
  });
});
