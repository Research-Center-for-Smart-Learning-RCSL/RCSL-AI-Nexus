'use client';

/**
 * Auth mode context. See docs/architecture/frontend.md section 3.
 *
 * The frontend is one build serving two entrances with different trust models.
 * Everything that differs between them is derived from a single `GET /admin/me`
 * call made once here, rather than from a build-time flag, because the same
 * image runs on both entrances.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import {
  api,
  isUnauthorized,
  UNAUTHORIZED_EVENT,
  UnauthorizedError,
} from '@/lib/api-client';

export type AuthMode = 'tailnet' | 'local' | 'dev';
export type Role =
  | 'admin'
  | 'tenant_admin'
  | 'operator'
  | 'curator'
  | 'auditor'
  | 'user';

/**
 * A single permission, mirroring `Scope` in the backend.
 *
 * Kept as a string union rather than validated against a list, because the
 * server is the only authority on what a scope means and an unknown one here
 * should narrow the UI, not break it.
 */
export type ScopeName = string;

export type Me = {
  /**
   * The user's own id. Absent from an earlier version, which forced callers
   * to substitute `login` wherever an id was needed: the self-deletion guard
   * compared a UUID to an email and so never matched, and new API keys were
   * attributed to a login string that will not join.
   */
  id: string;
  auth_mode: AuthMode;
  login: string;
  display_name: string;
  role: Role;
  /**
   * What this account may do, resolved server-side from the role.
   *
   * Optional so a frontend deployed against an older backend degrades rather
   * than crashing on parse. Absent is not the same as empty, and `can()`
   * treats it differently: an empty list means this account holds nothing, and
   * a missing one means the server did not say, in which case the old
   * `role === 'admin'` answer is used until it does.
   */
  scopes?: ScopeName[];
  /** null on the tailnet, which has no session at all. */
  session_expires_at: string | null;
};

export type SessionStatus =
  | 'loading'
  | 'authenticated'
  | 'unauthenticated'
  | 'error';

export type SessionValue = {
  me: Me | null;
  status: SessionStatus;
  error: Error | null;
  /**
   * Best available answer even when unauthenticated: a 401 body may carry the
   * entrance, otherwise the last successful value is reused. `null` means we
   * genuinely do not know yet.
   */
  authMode: AuthMode | null;
  /**
   * Whether this account holds a scope. **The** question to ask before showing
   * a control.
   *
   * `isAdmin` was the only question available until 2026-08-04 and was asked in
   * forty-five places, which works while there are two roles and misleads as
   * soon as there are six: an `operator` would have been shown a read-only
   * fleet it can in fact write, and an `auditor` an Invite button the server
   * refuses. Gating on the permission asks what the server will actually
   * decide.
   *
   * Still an affordance and not a control — security.md §5.2 — because every
   * request is checked again on arrival.
   */
  can: (scope: ScopeName) => boolean;
  /**
   * True only for the full platform administrator. Deliberately narrow: it now
   * means "holds every scope", so it is the right question for nothing except
   * the few places that really do mean *that* role. Prefer `can`.
   */
  isAdmin: boolean;
  hasSession: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
};

export const ME_QUERY_KEY = ['session', 'me'] as const;

const SessionContext = createContext<SessionValue | null>(null);

function fetchMe(): Promise<Me> {
  return api.get<Me>('/me');
}

/**
 * Remembered across a 401 so that the "what does a 401 mean" branch still works
 * after the session has gone. Module scope rather than state because it must
 * survive the provider remounting during a redirect.
 */
let lastKnownAuthMode: AuthMode | null = null;

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [unauthorizedHint, setUnauthorizedHint] = useState<AuthMode | null>(
    null,
  );

  const query = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: fetchMe,
    // A 401 here is an answer, not a transient failure worth retrying.
    retry: (failureCount, error) =>
      !isUnauthorized(error) && failureCount < 2,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });

  const { data, error, isPending } = query;

  useEffect(() => {
    if (data) lastKnownAuthMode = data.auth_mode;
  }, [data]);

  // Any 401 anywhere in the app invalidates what we believe about the session.
  useEffect(() => {
    function onUnauthorized(event: Event) {
      const detail = (event as CustomEvent<UnauthorizedError>).detail;
      const hinted = detail?.body?.auth_mode ?? null;
      if (hinted) {
        lastKnownAuthMode = hinted;
        setUnauthorizedHint(hinted);
      }
      queryClient.setQueryData(ME_QUERY_KEY, null);
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [queryClient]);

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
  }, [queryClient]);

  const signOut = useCallback(async () => {
    // Only meaningful on the public entrance; the tailnet has no session to end.
    //
    // The local clear-down happens whatever the server says. Previously a
    // rejected POST (missing CSRF cookie, a blip, a 5xx) skipped both the
    // cache clear and the redirect, and the caller discards the rejection, so
    // clicking Sign out on a shared machine did nothing visible while every
    // cached user list and key list stayed in memory on screen.
    try {
      await api.post('/auth/logout');
    } catch {
      // The server-side session may survive; the local one must not.
    } finally {
      queryClient.clear();
      lastKnownAuthMode = 'local';
      window.location.assign('/login');
    }
  }, [queryClient]);

  // A Set rather than an array scan: `can` is called on nearly every render of
  // every gated control, and rebuilding it per call would make the cheap
  // question the expensive one.
  const held = useMemo(() => new Set(data?.scopes ?? []), [data?.scopes]);

  /**
   * Whether the server told us anything about scopes at all.
   *
   * Absent means an older backend, and the frontend and backend are separate
   * images recreated independently — the last deploy recreated `admin-public`
   * alone — so frontend-ahead-of-backend is an ordering that really happens
   * here. Answering false for everything in that window would empty the nav
   * for every account including `admin`, bounce them off `/` to `/chat`, and
   * show no error explaining why: a management UI locked out by a deploy
   * order. Falling back to the old boolean keeps the previous behaviour until
   * the backend catches up.
   */
  const scopesReported = Array.isArray(data?.scopes);
  const isAdmin = data?.role === 'admin';

  const value = useMemo<SessionValue>(() => {
    let status: SessionStatus;
    if (data) status = 'authenticated';
    else if (isPending) status = 'loading';
    else if (isUnauthorized(error)) status = 'unauthenticated';
    else if (error) status = 'error';
    else status = 'unauthenticated';

    const authMode =
      data?.auth_mode ?? unauthorizedHint ?? lastKnownAuthMode ?? null;

    return {
      me: data ?? null,
      status,
      error: error ?? null,
      authMode,
      // Built from the list the server sent. When no list arrived at all, fall
      // back to the boolean this replaced rather than to "holds nothing" — see
      // `scopesReported`. Still false for everyone while the query is pending,
      // so controls fill in rather than flashing and disappearing.
      can: (scope: ScopeName) =>
        scopesReported ? held.has(scope) : Boolean(data) && isAdmin,
      isAdmin,
      hasSession: Boolean(data?.session_expires_at),
      refresh,
      signOut,
    };
  }, [data, error, isPending, unauthorizedHint, held, scopesReported, isAdmin, refresh, signOut]);

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error('useSession must be used inside a SessionProvider.');
  }
  return value;
}

/** Throws unless authenticated. For components already behind the gate. */
export function useMe(): Me {
  const { me } = useSession();
  if (!me) throw new Error('useMe used outside an authenticated subtree.');
  return me;
}

/**
 * Minutes remaining before the session expires, or null when the concept does
 * not apply (tailnet has no session). Ticks once a minute rather than once a
 * second: this drives a warning banner, not a countdown.
 */
export function useSessionExpiry(warnWithinMs = 5 * 60 * 1000) {
  const { me } = useSession();
  const expiresAt = me?.session_expires_at ?? null;
  const [now, setNow] = useState(() => Date.now());
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!expiresAt) return;
    timer.current = setInterval(() => setNow(Date.now()), 30_000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [expiresAt]);

  if (!expiresAt) return { msRemaining: null, shouldWarn: false, expired: false };

  const msRemaining = new Date(expiresAt).getTime() - now;
  return {
    msRemaining,
    shouldWarn: msRemaining > 0 && msRemaining <= warnWithinMs,
    expired: msRemaining <= 0,
  };
}
