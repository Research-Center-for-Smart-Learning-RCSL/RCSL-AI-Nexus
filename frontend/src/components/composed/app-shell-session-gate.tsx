import type { ReactNode } from 'react';

import { ErrorState } from '@/components/composed/error-state';
import { Spinner } from '@/components/composed/spinner';
import { TAILSCALE_CONNECTION_LOST } from '@/features/auth/messages';
import type { AuthMode, SessionStatus } from '@/lib/session';

type SessionGateState = {
  status: SessionStatus;
  authMode: AuthMode | null;
  error: Error | null;
  refresh: () => Promise<void>;
};

/** Returns undefined only when authenticated shell rendering may proceed. */
export function renderSessionGate({
  status,
  authMode,
  error,
  refresh,
}: SessionGateState): ReactNode | undefined {
  if (status === 'loading') {
    return (
      <div className="flex flex-1 flex-col items-center justify-center">
        {/* Decorative: the line below is the announcement, and labelling both
            reads the same sentence twice. */}
        <Spinner label={null} />
        <p role="status" className="text-sm text-muted-foreground">
          Checking your access…
        </p>
      </div>
    );
  }
  if (status === 'unauthenticated' && authMode === 'tailnet') {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <ErrorState
          title="Tailscale connection lost"
          error={TAILSCALE_CONNECTION_LOST}
          onRetry={() => void refresh()}
          className="max-w-md"
        />
      </div>
    );
  }
  if (status === 'error') {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <ErrorState
          title="Could not reach the admin API"
          error={error}
          onRetry={() => void refresh()}
          className="max-w-md"
        />
      </div>
    );
  }
  return undefined;
}
