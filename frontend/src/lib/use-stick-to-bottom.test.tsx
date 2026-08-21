import { useState } from 'react';
import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { useStickToBottom } from './use-stick-to-bottom';

/**
 * The assistant drawer renders nothing while it is closed, so its scroll
 * container arrives long after the component mounts. An earlier version of this
 * hook attached its observer from an effect with no dependencies, which ran
 * once against two nulls and never again — the drawer followed no reply it ever
 * streamed.
 */
const observed: Element[] = [];

class FakeResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe(target: Element) {
    observed.push(target);
    // The real one delivers an initial observation when it begins.
    this.callback([], this as unknown as ResizeObserver);
  }
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', FakeResizeObserver);

function Drawer() {
  const [open, setOpen] = useState(false);
  const { containerRef, contentRef, onScroll } = useStickToBottom();

  return (
    <div>
      <button type="button" onClick={() => setOpen((was) => !was)}>
        Toggle
      </button>
      {open ? (
        <div ref={containerRef} onScroll={onScroll} data-testid="scroller">
          <div ref={contentRef}>a reply</div>
        </div>
      ) : null}
    </div>
  );
}

afterEach(() => {
  observed.length = 0;
  cleanup();
});

describe('useStickToBottom', () => {
  it('observes content that appears after the component mounted', async () => {
    render(<Drawer />);
    expect(observed).toHaveLength(0);

    await userEvent.click(screen.getByRole('button', { name: 'Toggle' }));

    expect(observed).toHaveLength(1);
    expect(observed[0]).toHaveTextContent('a reply');
  });

  it('re-observes after the elements are unmounted and mounted again', async () => {
    render(<Drawer />);
    const toggle = screen.getByRole('button', { name: 'Toggle' });

    await userEvent.click(toggle);
    await userEvent.click(toggle);
    await userEvent.click(toggle);

    // Once for each time the drawer opened, never zero on the second open.
    expect(observed).toHaveLength(2);
  });
});
