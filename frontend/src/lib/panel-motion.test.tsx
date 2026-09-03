import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PANEL_MOTION_MS, usePanelMotion } from './panel-motion';

function Probe({ open, reduced, onExited }: { open: boolean; reduced: boolean | null; onExited?: () => void }) {
  const motion = usePanelMotion(open, reduced, onExited);
  return motion.mounted ? (
    <output data-state={motion.state} data-closing={motion.closing} />
  ) : null;
}

describe('panel motion lifecycle', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('keeps an exit mounted without relying on a transition event', () => {
    const exited = vi.fn();
    const view = render(<Probe open reduced={false} onExited={exited} />);
    const panel = screen.getByRole('status', { hidden: true });

    view.rerender(<Probe open={false} reduced={false} onExited={exited} />);
    expect(panel).toHaveAttribute('data-state', 'closed');
    expect(panel).toHaveAttribute('data-closing', 'true');

    panel.dispatchEvent(new Event('transitionend'));
    expect(panel).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(PANEL_MOTION_MS));
    expect(screen.queryByRole('status', { hidden: true })).toBeNull();
    expect(exited).toHaveBeenCalledOnce();
  });

  it('closes immediately when reduced motion is requested', () => {
    const exited = vi.fn();
    const view = render(<Probe open reduced onExited={exited} />);
    view.rerender(<Probe open={false} reduced onExited={exited} />);

    expect(screen.queryByRole('status', { hidden: true })).toBeNull();
    expect(exited).toHaveBeenCalledOnce();
  });

  it('cancels a pending exit when a rapid toggle reopens the panel', () => {
    const view = render(<Probe open reduced={false} />);
    view.rerender(<Probe open={false} reduced={false} />);
    view.rerender(<Probe open reduced={false} />);
    act(() => vi.advanceTimersByTime(PANEL_MOTION_MS));

    expect(screen.getByRole('status', { hidden: true })).toHaveAttribute(
      'data-state',
      'open',
    );
  });
});
