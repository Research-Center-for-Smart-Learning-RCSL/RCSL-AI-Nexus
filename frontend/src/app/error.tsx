'use client';

/**
 * The route-level error boundary.
 *
 * Without one, any render-time throw below the root layout falls through to
 * Next.js's own screen, which shares nothing with this product's typography or
 * language and tells an operator nothing they can act on.
 *
 * `reset()` re-renders the segment rather than reloading, so a failure caused by
 * one bad response recovers without losing the rest of the session.
 */

import { useEffect } from 'react';

import { ErrorState } from '@/components/composed/error-state';

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // The digest is the only handle on the server-side log entry for this
    // failure, so it goes to the console where an operator can quote it.
    console.error('Unhandled render error', error.digest ?? '', error);
  }, [error]);

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <ErrorState
        title="This screen stopped working"
        error={error}
        onRetry={reset}
        className="max-w-md"
      />
    </div>
  );
}
