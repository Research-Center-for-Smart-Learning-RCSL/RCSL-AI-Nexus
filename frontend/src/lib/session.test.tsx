import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { SessionProvider, useSession, type Me } from '@/lib/session';

/**
 * What `can` answers, and in particular what it answers when the server said
 * nothing about scopes.
 *
 * That case is not hypothetical here. The frontend and backend are separate
 * images recreated independently — one deploy recreated `admin-public` alone —
 * so a frontend newer than the backend it talks to is an ordering this
 * deployment actually produces. Answering "holds nothing" in that window would
 * empty the nav for every account including `admin`, bounce them off `/` to
 * `/chat`, and explain none of it. The distinction the code draws is between an
 * **absent** list and an **empty** one, which are one falsy value apart and
 * three lines apart in the implementation.
 */

const get = vi.fn();

vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return { ...actual, api: { ...actual.api, get: (...args: unknown[]) => get(...args) } };
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <SessionProvider>{children}</SessionProvider>
    </QueryClientProvider>
  );
}

function me(overrides: Partial<Me> = {}): Me {
  return {
    id: 'u1',
    auth_mode: 'local',
    login: 'someone@example.test',
    display_name: 'Someone',
    role: 'user',
    session_expires_at: null,
    ...overrides,
  };
}

async function signedInAs(who: Me) {
  get.mockResolvedValue(who);
  const rendered = renderHook(() => useSession(), { wrapper });
  await waitFor(() => expect(rendered.result.current.status).toBe('authenticated'));
  return rendered;
}

beforeEach(() => {
  get.mockReset();
});

describe('can', () => {
  it('answers from the list the server sent', async () => {
    const { result } = await signedInAs(
      me({ role: 'operator', scopes: ['model:read', 'node:read'] }),
    );

    expect(result.current.can('model:read')).toBe(true);
    expect(result.current.can('model:write')).toBe(false);
  });

  it('holds nothing when the list is empty, even for an admin', async () => {
    // An empty list is the server's answer, not its silence, and it is the one
    // case where `role` must not override what was said.
    const { result } = await signedInAs(me({ role: 'admin', scopes: [] }));

    expect(result.current.can('user:read')).toBe(false);
    expect(result.current.isAdmin).toBe(true);
  });

  it('falls back to the administrator answer when no list arrived at all', async () => {
    // A backend older than the scopes field. The fallback is the boolean this
    // replaced, so an admin keeps working until the other image catches up.
    const { result } = await signedInAs(me({ role: 'admin' }));

    expect(result.current.can('user:read')).toBe(true);
    expect(result.current.can('anything:at:all')).toBe(true);
  });

  it('grants a non-admin nothing when no list arrived at all', async () => {
    // The other half of the same fallback, and the one that keeps it from being
    // an escalation: silence must not promote anyone.
    const { result } = await signedInAs(me({ role: 'operator' }));

    expect(result.current.can('model:read')).toBe(false);
  });

  it('answers false for everyone while the session is still loading', async () => {
    // Not "true briefly, then false": a control that renders and disappears is
    // worse than one that fills in, and a control that renders because the
    // answer is not known yet is the wrong side to be wrong on.
    get.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useSession(), { wrapper });

    expect(result.current.status).toBe('loading');
    expect(result.current.can('chat:use')).toBe(false);
  });
});
