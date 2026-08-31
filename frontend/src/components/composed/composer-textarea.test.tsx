import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
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
});
