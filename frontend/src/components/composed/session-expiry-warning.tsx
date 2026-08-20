'use client';

import { useState } from 'react';

import { useSession, useSessionExpiry } from '@/lib/session';
import { Button } from '@/components/ui/button';

/**
 * The end-of-session warning.
 *
 * `session_expires_at` is the **absolute** expiry, fixed at login and never
 * moved: the store extends the idle window on every read but deliberately does
 * not touch this deadline. So there is no "stay signed in" to offer — a button
 * promising one would do nothing and then the session would end anyway.
 *
 * What can be offered is the choice of moment. Signing back in now, before the
 * deadline, is the difference between losing a half-written form deliberately
 * and losing it mid-sentence. The notice can be dismissed, because for most of
 * the warning window there is nothing to do about it, and it comes back for the
 * last minute regardless of that dismissal.
 */
export function SessionExpiryWarning() {
  const { msRemaining, shouldWarn } = useSessionExpiry();
  const { signOut } = useSession();
  const [dismissed, setDismissed] = useState(false);

  if (!shouldWarn || msRemaining === null) return null;
  const urgent = msRemaining <= 60_000;
  if (dismissed && !urgent) return null;

  const minutes = Math.max(1, Math.round(msRemaining / 60_000));
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b bg-amber-500/10 px-4 py-2 text-sm"
    >
      <span>
        Your session ends in about {minutes} minute{minutes === 1 ? '' : 's'}.
        This deadline is fixed at sign-in and cannot be extended.
      </span>
      <div className="ml-auto flex items-center gap-2">
        <Button size="xs" variant="outline" onClick={() => void signOut()}>
          Sign in again now
        </Button>
        {!urgent ? (
          <Button size="xs" variant="ghost" onClick={() => setDismissed(true)}>
            Dismiss
          </Button>
        ) : null}
      </div>
    </div>
  );
}
