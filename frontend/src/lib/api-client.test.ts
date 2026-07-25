import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ApiError,
  UNAUTHORIZED_EVENT,
  UnauthorizedError,
  NetworkError,
  api,
  apiRequest,
  readCookie,
} from '@/lib/api-client';

const CSRF_COOKIE = '__Host-nexus_csrf';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** The Headers object fetch was actually called with, for the last call. */
function lastInit(): RequestInit {
  const mock = fetch as unknown as ReturnType<typeof vi.fn>;
  return mock.mock.calls[mock.mock.calls.length - 1][1] as RequestInit;
}

function clearCookies(): void {
  for (const part of document.cookie.split(';')) {
    const name = part.split('=')[0].trim();
    if (name) {
      document.cookie = `${name}=; Secure; Path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
    }
  }
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  clearCookies();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('readCookie', () => {
  it('returns the value of a named cookie and null when absent', () => {
    document.cookie = `${CSRF_COOKIE}=token-123; Secure; Path=/`;
    expect(readCookie(CSRF_COOKIE)).toBe('token-123');
    expect(readCookie('nonexistent')).toBeNull();
  });
});

describe('apiRequest CSRF and header rules', () => {
  it('attaches the CSRF header from the cookie on a mutation', async () => {
    document.cookie = `${CSRF_COOKIE}=token-123; Secure; Path=/`;
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({}));

    await api.post('/models', { reference: 'llama3' });

    const init = lastInit();
    const headers = init.headers as Headers;
    expect(headers.get('X-CSRF-Token')).toBe('token-123');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
  });

  it('never attaches an Authorization header', async () => {
    document.cookie = `${CSRF_COOKIE}=token-123; Secure; Path=/`;
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({}));

    await api.post('/models', { reference: 'llama3' });

    expect((lastInit().headers as Headers).has('Authorization')).toBe(false);
  });

  it('sends no CSRF header on a GET', async () => {
    document.cookie = `${CSRF_COOKIE}=token-123; Secure; Path=/`;
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse([]));

    await api.get('/models');

    expect((lastInit().headers as Headers).has('X-CSRF-Token')).toBe(false);
  });

  it('sends no CSRF header on a mutation when the cookie is absent', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({}));

    await api.post('/models', { reference: 'llama3' });

    expect((lastInit().headers as Headers).has('X-CSRF-Token')).toBe(false);
  });
});

describe('apiRequest error handling', () => {
  it('throws UnauthorizedError and broadcasts the event on a 401', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ message: 'Session expired', auth_mode: 'local' }, 401),
    );
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    await expect(apiRequest('/me')).rejects.toBeInstanceOf(UnauthorizedError);
    expect(listener).toHaveBeenCalledTimes(1);

    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });

  it('throws a plain ApiError with the status on other failures', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ message: 'Not found' }, 404),
    );

    await expect(apiRequest('/models/9')).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
    });
    // A 404 is an ApiError but not the 401 subclass.
    const error = await apiRequest('/models/9').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeInstanceOf(UnauthorizedError);
  });

  it('wraps a transport failure as a NetworkError', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new TypeError('offline'));

    await expect(apiRequest('/models')).rejects.toBeInstanceOf(NetworkError);
  });

  it('propagates an abort without wrapping it', async () => {
    const abort = new DOMException('aborted', 'AbortError');
    (fetch as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(abort);

    await expect(apiRequest('/models')).rejects.toBe(abort);
  });
});
