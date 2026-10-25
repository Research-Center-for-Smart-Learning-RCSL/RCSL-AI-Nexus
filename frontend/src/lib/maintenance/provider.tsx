'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { MAINTENANCE_EVENT } from '@/lib/api-client';
import { ME_QUERY_KEY } from '@/lib/session/query';

import {
  fetchMaintenanceStatus,
  MAINTENANCE_STATUS_QUERY_KEY,
  type MaintenanceStatus,
} from './query';

/**
 * How often an open page re-reads the hold. A proposed UI target, not a
 * deadline: the server refuses the moment the hold lands whatever this says,
 * and any request refused with `maintenance` triggers a re-read at once.
 */
export const MAINTENANCE_POLL_MS = 5_000;

export type MaintenanceValue = {
  /** Null until the first answer. Never assumed open before it arrives. */
  status: MaintenanceStatus | null;
  /** False until the first answer, too; read `status` to tell unknown apart. */
  closed: boolean;
  /** The status endpoint could not be read at all. */
  unavailable: boolean;
  /** Why it could not, while `unavailable`. */
  error: Error | null;
  refresh: () => Promise<void>;
};

const MaintenanceContext = createContext<MaintenanceValue | null>(null);

export function MaintenanceProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: MAINTENANCE_STATUS_QUERY_KEY,
    queryFn: fetchMaintenanceStatus,
    refetchInterval: MAINTENANCE_POLL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: MAINTENANCE_STATUS_QUERY_KEY });
  }, [queryClient]);

  useEffect(() => {
    function onMaintenance() {
      void refresh();
    }
    window.addEventListener(MAINTENANCE_EVENT, onMaintenance);
    return () => window.removeEventListener(MAINTENANCE_EVENT, onMaintenance);
  }, [refresh]);

  // A transition in either direction changes who this browser is allowed to
  // be: closing signs non-administrators out, reopening needs them to sign in
  // again. Identity is re-read both ways rather than inferred.
  const closed = query.data?.closed ?? false;
  const previous = useRef<boolean | null>(null);
  useEffect(() => {
    if (query.data === undefined) return;
    if (previous.current !== null && previous.current !== closed) {
      void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
    }
    previous.current = closed;
  }, [closed, query.data, queryClient]);

  const value = useMemo<MaintenanceValue>(
    () => ({
      status: query.data ?? null,
      closed,
      unavailable: query.data === undefined && query.isError,
      error: query.data === undefined ? query.error : null,
      refresh,
    }),
    [query.data, query.isError, query.error, closed, refresh],
  );

  return <MaintenanceContext.Provider value={value}>{children}</MaintenanceContext.Provider>;
}

export function useMaintenance(): MaintenanceValue {
  const value = useContext(MaintenanceContext);
  if (!value) throw new Error('useMaintenance outside MaintenanceProvider');
  return value;
}
