import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AssistantComposer } from './assistant-composer';

const baseProps = {
  question: 'How should I configure this?',
  setQuestion: vi.fn(),
  isStreaming: false,
  onSubmit: vi.fn(),
  onCancel: vi.fn(),
};

describe('AssistantComposer', () => {
  it('keeps only the primary question and Ask action in the footer', () => {
    render(<AssistantComposer {...baseProps} />);

    expect(screen.getByRole('textbox', { name: 'Ask the assistant' }).tagName).toBe(
      'TEXTAREA',
    );
    expect(screen.getByRole('button', { name: 'Ask' })).toHaveClass('min-w-12');
    expect(screen.queryByRole('button', { name: /clear/i })).not.toBeInTheDocument();
  });

  it('uses the same action width when Stop replaces Ask', () => {
    const { rerender } = render(<AssistantComposer {...baseProps} />);
    const ask = screen.getByRole('button', { name: 'Ask' });
    expect(ask).toHaveClass('min-w-12');

    rerender(<AssistantComposer {...baseProps} isStreaming />);

    expect(screen.queryByRole('button', { name: 'Ask' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stop' })).toHaveClass('min-w-12');
    expect(screen.getByRole('textbox', { name: 'Ask the assistant' })).toBeDisabled();
  });
});
