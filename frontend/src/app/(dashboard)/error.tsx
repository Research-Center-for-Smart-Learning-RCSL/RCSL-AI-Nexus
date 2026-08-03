'use client';

/**
 * Errors from a dashboard screen, caught inside the shell.
 *
 * The root boundary wraps this group's layout rather than nesting inside it, so
 * a throw on /models replaced the whole application — nav included — and left
 * the operator on an error page whose only way out was the browser's Back
 * button. This one renders where the page would have, next to the nav they were
 * using, which is the same reasoning as `loading.tsx` beside it.
 *
 * The root boundary stays for what this cannot catch: a failure in the shell
 * itself, including the session gate every one of these screens sits behind.
 */

import { useEffect } from 'react';

import { ErrorState } from '@/components/composed/error-state';

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Unhandled render error', error.digest ?? '', error);
  }, [error]);

  return (
    <div className="flex flex-1 items-center justify-center py-16">
      <ErrorState
        title="This screen stopped working"
        error={error}
        onRetry={reset}
        className="max-w-md"
      />
    </div>
  );
}
