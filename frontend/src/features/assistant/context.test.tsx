import { describe, expect, it } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { useState, type ReactNode } from 'react';

import {
  AssistantContextProvider,
  useAssistantContext,
  useAssistantSurface,
} from '@/features/assistant/context';
import type { AssistSurface } from '@/features/assistant/schema';

/**
 * Screens nest, and the registry has to survive it.
 *
 * The key table stays mounted while a dialog on top of it registers a different
 * surface, so this is not a race but the ordinary path. With a single slot the
 * dialog's cleanup reset everything to `other` on close and the table beneath
 * never re-registered — its effect dependencies had not changed — so closing a
 * dialog silently took the assistant's context away from the screen still in
 * front of the operator, while both call sites' comments claimed the opposite.
 */

function Screen({
  surface,
  draft,
  applies,
}: {
  surface: AssistSurface;
  draft?: string;
  applies?: boolean;
}) {
  useAssistantSurface({
    surface,
    readDraft: draft === undefined ? undefined : () => ({ name: draft }),
    applyPatch: applies ? () => {} : undefined,
  });
  return null;
}

function Probe() {
  const { surface, canApply, readDraft } = useAssistantContext();
  return (
    <div>
      <span data-testid="surface">{surface}</span>
      <span data-testid="can-apply">{String(canApply)}</span>
      <span data-testid="draft">{readDraft()?.name ?? 'none'}</span>
    </div>
  );
}

function Harness({ children }: { children: ReactNode }) {
  return (
    <AssistantContextProvider>
      {children}
      <Probe />
    </AssistantContextProvider>
  );
}

const surface = () => screen.getByTestId('surface').textContent;
const canApply = () => screen.getByTestId('can-apply').textContent;
const draft = () => screen.getByTestId('draft').textContent;

describe('the assistant registry', () => {
  it('starts with no screen registered', () => {
    render(<Harness>{null}</Harness>);

    expect(surface()).toBe('other');
    expect(canApply()).toBe('false');
  });

  it('restores the screen underneath when a dialog closes', () => {
    function App() {
      const [open, setOpen] = useState(false);
      return (
        <Harness>
          <Screen surface="api_keys.list" />
          {open ? <Screen surface="api_keys.create" draft="ci" applies /> : null}
          <button type="button" onClick={() => setOpen(!open)}>
            toggle
          </button>
        </Harness>
      );
    }
    render(<App />);
    expect(surface()).toBe('api_keys.list');

    act(() => screen.getByText('toggle').click());
    expect(surface()).toBe('api_keys.create');
    expect(canApply()).toBe('true');

    act(() => screen.getByText('toggle').click());
    // Not `other`. The table is still on screen and still the thing the
    // operator is asking about.
    expect(surface()).toBe('api_keys.list');
    expect(canApply()).toBe('false');
  });

  it('reports no draft for a screen that has no form', () => {
    // `undefined`, not `{}`. An empty object is indistinguishable from a form
    // the operator opened and left blank, and the backend would then describe
    // an empty key form to the model while it is being asked about the docs.
    render(
      <Harness>
        <Screen surface="api_docs" />
      </Harness>,
    );

    expect(draft()).toBe('none');
  });

  it('reads the draft of the topmost screen', () => {
    render(
      <Harness>
        <Screen surface="api_keys.list" />
        <Screen surface="api_keys.create" draft="ci" applies />
      </Harness>,
    );

    expect(draft()).toBe('ci');
  });

  it('unregisters a screen that unmounts on its own', () => {
    function App() {
      const [mounted, setMounted] = useState(true);
      return (
        <Harness>
          {mounted ? <Screen surface="api_keys.edit" /> : null}
          <button type="button" onClick={() => setMounted(false)}>
            unmount
          </button>
        </Harness>
      );
    }
    render(<App />);
    expect(surface()).toBe('api_keys.edit');

    act(() => screen.getByText('unmount').click());
    expect(surface()).toBe('other');
  });
});
