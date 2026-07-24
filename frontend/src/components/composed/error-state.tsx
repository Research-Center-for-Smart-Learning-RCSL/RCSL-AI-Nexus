'use client';

import { AlertTriangleIcon } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ApiError, NetworkError } from '@/lib/api-client';

export type ErrorStateProps = {
  title?: string;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
};

/**
 * Error text is taken from the API response when there is one. The backend
 * already decides how much to disclose (backend.md section 5), so the UI does
 * not paraphrase it.
 */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof NetworkError) return error.message;
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return 'Something went wrong.';
}

export function ErrorState({
  title = 'Could not load this',
  error,
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      data-slot="error-state"
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-6 py-10 text-center',
        className,
      )}
    >
      <AlertTriangleIcon className="size-5 text-destructive" />
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        <p className="max-w-prose text-sm text-muted-foreground">
          {describeError(error)}
        </p>
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
