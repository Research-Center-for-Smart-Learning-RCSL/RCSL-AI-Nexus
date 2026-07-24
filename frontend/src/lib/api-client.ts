/**
 * The single entry point for every call to the admin API.
 *
 * Two rules from docs/architecture/frontend.md section 3 are enforced here so
 * that no feature module can forget them:
 *
 *  1. There is never an `Authorization` header. Identity is either a Tailscale
 *     header the browser never sees, or a server-side session cookie. The
 *     frontend holds no token.
 *  2. Every non-GET request echoes the CSRF value from the non-HttpOnly
 *     companion cookie (security.md section 5.3, double submit). The tailnet
 *     entrance has no such cookie and simply sends no header, which is correct:
 *     it has no ambient credential to protect.
 *
 * All calls are same-origin because next.config.js rewrites `/admin/*` to the
 * entrance's backend.
 */

/** Prefix that the Next.js rewrite forwards to `ADMIN_API_URL`. */
export const API_BASE = '/admin';

/**
 * Must match the backend. Kept configurable because the two entrances are
 * deployed from the same image and only differ by environment.
 */
export const CSRF_COOKIE =
  process.env.NEXT_PUBLIC_CSRF_COOKIE ?? '__Host-nexus_csrf';
export const CSRF_HEADER =
  process.env.NEXT_PUBLIC_CSRF_HEADER ?? 'X-CSRF-Token';

/** Broadcast on every 401 so the session layer can branch without polling. */
export const UNAUTHORIZED_EVENT = 'nexus:unauthorized';

export type ApiErrorBody = {
  code?: string;
  message?: string;
  detail?: unknown;
  /** Some 401 bodies carry the entrance so a logged-out UI can still branch. */
  auth_mode?: 'tailnet' | 'local' | 'dev';
};

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly body: ApiErrorBody | null;

  constructor(status: number, message: string, body: ApiErrorBody | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body?.code;
    this.body = body;
  }
}

/**
 * Thrown for 401 only. Callers branch on `instanceof UnauthorizedError` rather
 * than on a status number, and the session layer decides what a 401 means:
 * "Tailscale connection lost" on the tailnet, "go to the login screen" locally.
 */
export class UnauthorizedError extends ApiError {
  constructor(message: string, body: ApiErrorBody | null) {
    super(401, message, body);
    this.name = 'UnauthorizedError';
  }
}

/** Network failure or an aborted request: no HTTP response was produced. */
export class NetworkError extends Error {
  readonly cause?: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'NetworkError';
    this.cause = cause;
  }
}

export function isUnauthorized(error: unknown): error is UnauthorizedError {
  return error instanceof UnauthorizedError;
}

export function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const prefix = `${encodeURIComponent(name)}=`;
  for (const part of document.cookie.split('; ')) {
    if (part.startsWith(prefix)) {
      return decodeURIComponent(part.slice(prefix.length));
    }
  }
  return null;
}

export type QueryValue = string | number | boolean | null | undefined;

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** Serialised as JSON unless it is already a FormData or a string. */
  body?: unknown;
  query?: Record<string, QueryValue>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const normalised = path.startsWith('/') ? path : `/${path}`;
  const url = `${API_BASE}${normalised}`;
  if (!query) return url;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

function buildHeaders(
  method: string,
  body: unknown,
  extra?: Record<string, string>,
): Headers {
  const headers = new Headers(extra);
  headers.set('Accept', 'application/json');

  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  if (body !== undefined && !isForm && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  // Double-submit CSRF. Absent on the tailnet entrance by design.
  if (method !== 'GET' && method !== 'HEAD') {
    const token = readCookie(CSRF_COOKIE);
    if (token) headers.set(CSRF_HEADER, token);
  }

  // Deliberately no Authorization header, ever. See the module docstring.
  return headers;
}

function encodeBody(body: unknown): BodyInit | undefined {
  if (body === undefined) return undefined;
  if (typeof body === 'string') return body;
  if (typeof FormData !== 'undefined' && body instanceof FormData) return body;
  return JSON.stringify(body);
}

async function readErrorBody(response: Response): Promise<ApiErrorBody | null> {
  try {
    const text = await response.text();
    if (!text) return null;
    const parsed: unknown = JSON.parse(text);
    if (parsed && typeof parsed === 'object') return parsed as ApiErrorBody;
    return { message: text };
  } catch {
    return null;
  }
}

function messageFor(status: number, body: ApiErrorBody | null): string {
  if (body?.message) return body.message;
  if (typeof body?.detail === 'string') return body.detail;
  return `Request failed with status ${status}.`;
}

function notifyUnauthorized(error: UnauthorizedError): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT, { detail: error }));
}

/**
 * Performs the request and returns the raw `Response`. Used directly by the
 * chat stream reader, which must not consume the body as JSON.
 *
 * Non-2xx responses still throw, so a stream that fails before the first byte
 * looks like any other error. A failure *after* the first byte cannot be
 * reported this way; see features/chat/stream.ts.
 */
export async function apiRequest(
  path: string,
  options: RequestOptions = {},
): Promise<Response> {
  const method = options.method ?? 'GET';
  let response: Response;

  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      // Same-origin thanks to the rewrite, but stated explicitly so the intent
      // survives any future change to how the app is served.
      credentials: 'include',
      headers: buildHeaders(method, options.body, options.headers),
      body: encodeBody(options.body),
      signal: options.signal,
      cache: 'no-store',
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new NetworkError('Could not reach the server.', cause);
  }

  if (response.ok) return response;

  const body = await readErrorBody(response);
  if (response.status === 401) {
    const error = new UnauthorizedError(messageFor(401, body), body);
    notifyUnauthorized(error);
    throw error;
  }
  throw new ApiError(response.status, messageFor(response.status, body), body);
}

/** Performs the request and decodes a JSON response. `204` yields `undefined`. */
export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const response = await apiRequest(path, options);
  if (response.status === 204) return undefined as T;

  const text = await response.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiFetch<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: 'DELETE' }),
};
