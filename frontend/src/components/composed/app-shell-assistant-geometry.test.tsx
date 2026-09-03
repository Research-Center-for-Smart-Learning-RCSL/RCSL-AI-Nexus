import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { RESERVED_CLASS, WIDTH_EVENT } from '@/features/assistant/width';

import { assistantState, SCOPES, signedInWith, TestAppShell } from './app-shell-test-support';

function shell() {
  const element = document.querySelector('.h-\\[100dvh\\]');
  if (!(element instanceof HTMLDivElement)) throw new Error('Shell was not rendered.');
  return element;
}

describe('assistant desktop reserved-width geometry', () => {
  it('reserves exactly the narrow drawer width while it is open and removes it on close', () => {
    signedInWith(SCOPES.user, '/chat');
    assistantState.isOpen = true;
    const view = render(<TestAppShell>content</TestAppShell>);

    expect(shell()).toHaveClass(RESERVED_CLASS.narrow);
    assistantState.isOpen = false;
    view.rerender(<TestAppShell>content</TestAppShell>);
    expect(shell()).not.toHaveClass(RESERVED_CLASS.narrow);
    expect(shell()).not.toHaveClass(RESERVED_CLASS.wide);
  });

  it('tracks the persisted widened preference without adding an overlay reservation', () => {
    signedInWith(SCOPES.user, '/chat');
    assistantState.isOpen = true;
    const view = render(<TestAppShell>content</TestAppShell>);

    window.dispatchEvent(new CustomEvent(WIDTH_EVENT, { detail: true }));
    view.rerender(<TestAppShell>content</TestAppShell>);
    expect(shell()).toHaveClass(RESERVED_CLASS.wide);
    expect(shell()).not.toHaveClass(RESERVED_CLASS.narrow);
  });
});
