import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CodeBlock } from './code-block';

describe('CodeBlock copy feedback', () => {
  afterEach(() => vi.restoreAllMocks());

  it('updates the shared opacity-only icon state as soon as copying succeeds', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    const user = userEvent.setup();
    render(<CodeBlock code="curl https://gateway.example" label="Copy example" />);

    const button = screen.getByRole('button', { name: 'Copy example' });
    const feedback = button.querySelector<HTMLElement>('[data-copied]');
    if (!feedback) throw new Error('Expected copy feedback icon.');
    expect(feedback).toHaveAttribute('data-copied', 'false');

    await user.click(button);

    expect(writeText).toHaveBeenCalledWith('curl https://gateway.example');
    await waitFor(() => expect(feedback).toHaveAttribute('data-copied', 'true'));
    expect(feedback).toHaveClass('nexus-copy-feedback');
    expect(feedback.querySelectorAll('svg')).toHaveLength(2);
    expect(await screen.findByText('Copied to the clipboard.')).toHaveAttribute(
      'aria-live',
      'polite',
    );
  });
});
