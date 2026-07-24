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
export type Role = 'admin' | 'user';

export type Me = {
  auth_mode: AuthMode;
  login: string;
  display_name: string;
  role: Role;
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
  /** Convenience flags. Role gating in the UI is an affordance, not a control. */
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
    await api.post('/auth/logout');
    queryClient.clear();
    lastKnownAuthMode = 'local';
    window.location.assign('/login');
  }, [queryClient]);

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
      isAdmin: data?.role === 'admin',
      hasSession: Boolean(data?.session_expires_at),
      refresh,
      signOut,
    };
  }, [data, error, isPending, unauthorizedHint, refresh, signOut]);

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
