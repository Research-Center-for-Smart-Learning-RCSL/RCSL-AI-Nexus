'use client';

import { createContext, useContext } from 'react';

import type { Me, SessionValue } from './types';

export const SessionContext = createContext<SessionValue | null>(null);

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
