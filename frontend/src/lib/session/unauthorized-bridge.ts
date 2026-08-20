'use client';

import { useEffect, type Dispatch, type SetStateAction } from 'react';
import type { QueryClient } from '@tanstack/react-query';

import { UNAUTHORIZED_EVENT, UnauthorizedError } from '@/lib/api-client';

import { ME_QUERY_KEY } from './query';
import type { AuthMode } from './types';

let lastKnownAuthMode: AuthMode | null = null;

export function rememberAuthMode(mode: AuthMode): void {
  lastKnownAuthMode = mode;
}

export function readRememberedAuthMode(): AuthMode | null {
  return lastKnownAuthMode;
}

export function useUnauthorizedBridge(
  queryClient: QueryClient,
  setUnauthorizedHint: Dispatch<SetStateAction<AuthMode | null>>,
): void {
  useEffect(() => {
    function onUnauthorized(event: Event) {
      const detail = (event as CustomEvent<UnauthorizedError>).detail;
      const hinted = detail?.body?.auth_mode ?? null;
      if (hinted) {
        rememberAuthMode(hinted);
        setUnauthorizedHint(hinted);
      }
      queryClient.setQueryData(ME_QUERY_KEY, null);
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [queryClient, setUnauthorizedHint]);
}
