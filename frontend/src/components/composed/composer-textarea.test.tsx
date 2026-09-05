import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ComposerTextarea } from './composer-textarea';

function ComposerHarness({ onSubmit }: { onSubmit: () => void }) {
  const [value, setValue] = useState('');

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <ComposerTextarea
        aria-label="Message"
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
    </form>
  );
}

describe('ComposerTextarea', () => {
  it('keeps Shift+Enter for a new line and uses Enter to submit', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<ComposerHarness onSubmit={onSubmit} />);

    const message = screen.getByRole('textbox', { name: 'Message' });
    await user.type(message, 'First line{Shift>}{Enter}{/Shift}Second line');

    expect(message).toHaveValue('First line\nSecond line');
    expect(onSubmit).not.toHaveBeenCalled();

    await user.type(message, '{Enter}');
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it('does not submit while an IME candidate is being committed', () => {
    const onSubmit = vi.fn();
    render(<ComposerHarness onSubmit={onSubmit} />);
    const message = screen.getByRole('textbox', { name: 'Message' });

    fireEvent.keyDown(message, { key: 'Enter', isComposing: true });
    fireEvent.keyDown(message, { key: 'Enter', keyCode: 229 });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('caps its automatic height and scrolls longer messages internally', async () => {
    const { rerender } = render(
      <ComposerTextarea aria-label="Message" value="Short" onChange={() => undefined} />,
    );
    const message = screen.getByRole('textbox', { name: 'Message' });

    Object.defineProperty(message, 'scrollHeight', {
      configurable: true,
      value: 180,
    });
    rerender(
      <ComposerTextarea aria-label="Message" value="A longer message" onChange={() => undefined} />,
    );

    await waitFor(() => {
      expect(message).toHaveStyle({ height: '128px', overflowY: 'auto' });
    });
  });

  it('recalculates an unchanged draft when its available width changes', () => {
    let resizeCallback: ResizeObserverCallback | undefined;
    const disconnect = vi.fn();
    vi.stubGlobal(
      'ResizeObserver',
      class ResizeObserverMock {
        constructor(callback: ResizeObserverCallback) {
          resizeCallback = callback;
        }

        observe() {}
        unobserve() {}
        disconnect() {
          disconnect();
        }
      },
    );

    const { unmount } = render(
      <ComposerTextarea aria-label="Message" value="Same draft" onChange={() => undefined} />,
    );
    const message = screen.getByRole('textbox', { name: 'Message' });
    Object.defineProperty(message, 'scrollHeight', {
      configurable: true,
      value: 96,
    });

    act(() => {
      resizeCallback?.(
        [{ contentRect: { width: 180 } } as ResizeObserverEntry],
        {} as ResizeObserver,
      );
    });

    expect(message).toHaveStyle({ height: '96px', overflowY: 'hidden' });
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });
});
