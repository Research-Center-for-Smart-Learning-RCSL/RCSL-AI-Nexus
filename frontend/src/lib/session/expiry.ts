'use client';

import { useEffect, useRef, useState } from 'react';

import { useSession } from './context';

/** Session warning timer; tailnet sessions return the non-applicable state. */
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
