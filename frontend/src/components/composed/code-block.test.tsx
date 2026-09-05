import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CodeBlock } from './code-block';

const mocks = vi.hoisted(() => ({
  copied: false,
  copy: vi.fn(),
}));

vi.mock('@/lib/use-copy-to-clipboard', () => ({
  useCopyToClipboard: () => ({ copied: mocks.copied, copy: mocks.copy }),
}));

describe('CodeBlock copy feedback', () => {
  beforeEach(() => {
    mocks.copied = false;
    mocks.copy.mockReset();
  });

  it('presents the shared icon state and polite success status immediately', () => {
    const { rerender } = render(
      <CodeBlock code="curl https://gateway.example" label="Copy example" />,
    );

    const button = screen.getByRole('button', { name: 'Copy example' });
    const feedback = button.querySelector<HTMLElement>('[data-copied]');
    if (!feedback) throw new Error('Expected copy feedback icon.');
    expect(feedback).toHaveAttribute('data-copied', 'false');

    mocks.copied = true;
    rerender(<CodeBlock code="curl https://gateway.example" label="Copy example" />);

    expect(feedback).toHaveAttribute('data-copied', 'true');
    expect(feedback).toHaveClass('nexus-copy-feedback');
    expect(feedback.querySelectorAll('svg')).toHaveLength(2);
    expect(screen.getByText('Copied to the clipboard.')).toHaveAttribute(
      'aria-live',
      'polite',
    );
  });
});
