'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { api, isMaintenance, isUnauthorized } from '@/lib/api-client';

import { SessionContext } from './context';
import { fetchMe, ME_QUERY_KEY } from './query';
import {
  readRememberedAuthMode,
  rememberAuthMode,
  useUnauthorizedBridge,
} from './unauthorized-bridge';
import type { AuthMode, ScopeName, SessionStatus, SessionValue } from './types';

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [unauthorizedHint, setUnauthorizedHint] = useState<AuthMode | null>(null);
  const query = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: fetchMe,
    retry: (failureCount, error) =>
      !isUnauthorized(error) && !isMaintenance(error) && failureCount < 2,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });
  const { error, isPending } = query;
  // A `/me` refused with `maintenance` means the server no longer admits this
  // identity under its live role (#61). TanStack Query keeps the last
  // successful answer beside the error, so that answer is dropped here rather
  // than left to keep an account that was an administrator in the shell.
  const data = isMaintenance(error) ? undefined : query.data;

  useEffect(() => {
    if (data) rememberAuthMode(data.auth_mode);
  }, [data]);
  useUnauthorizedBridge(queryClient, setUnauthorizedHint);

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
  }, [queryClient]);

  const signOut = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      // Local state must still be cleared when server-side logout fails.
    } finally {
      queryClient.clear();
      rememberAuthMode('local');
      window.location.assign('/login');
    }
  }, [queryClient]);

  const held = useMemo(() => new Set(data?.scopes ?? []), [data?.scopes]);
  const scopesReported = Array.isArray(data?.scopes);
  const isAdmin = data?.role === 'admin';

  const value = useMemo<SessionValue>(() => {
    let status: SessionStatus;
    if (data) status = 'authenticated';
    else if (isPending) status = 'loading';
    else if (isUnauthorized(error) || isMaintenance(error)) status = 'unauthenticated';
    else if (error) status = 'error';
    else status = 'unauthenticated';

    const authMode =
      data?.auth_mode ?? unauthorizedHint ?? readRememberedAuthMode() ?? null;
    return {
      me: data ?? null,
      status,
      error: error ?? null,
      authMode,
      can: (scope: ScopeName) =>
        scopesReported ? held.has(scope) : Boolean(data) && isAdmin,
      isAdmin,
      hasSession: Boolean(data?.session_expires_at),
      refresh,
      signOut,
    };
  }, [
    data,
    error,
    isPending,
    unauthorizedHint,
    held,
    scopesReported,
    isAdmin,
    refresh,
    signOut,
  ]);

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}
