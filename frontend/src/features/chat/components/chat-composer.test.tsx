import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ChatComposer } from './chat-composer';

const baseProps = {
  capability: 'chat' as const,
  setCapability: vi.fn(),
  thinking: true,
  setThinking: vi.fn(),
  prompt: 'Explain this model',
  setPrompt: vi.fn(),
  useKnowledge: false,
  setUseKnowledge: vi.fn(),
  isStreaming: false,
  gatewayLoading: false,
  servable: new Set(['chat']),
  onSubmit: vi.fn(),
  onCancel: vi.fn(),
};

describe('ChatComposer', () => {
  it('keeps settings separate from the full-width writing row', () => {
    render(<ChatComposer {...baseProps} />);

    const message = screen.getByRole('textbox', { name: 'Message' });
    const capability = screen.getByRole('combobox', { name: 'Capability' });

    expect(message.tagName).toBe('TEXTAREA');
    expect(message.closest('[data-slot="chat-composer-writing"]')).not.toBeNull();
    expect(capability.closest('[data-slot="chat-composer-settings"]')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: /clear/i })).not.toBeInTheDocument();
  });

  it('replaces Send with Stop without leaving editable settings behind', () => {
    render(<ChatComposer {...baseProps} isStreaming />);

    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stop' })).toBeEnabled();
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled();
    expect(
      screen.getByRole('checkbox', { name: 'Answer from the knowledge base' }),
    ).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Thinking' })).toBeDisabled();
  });
});
