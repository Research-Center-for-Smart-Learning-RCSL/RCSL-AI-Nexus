'use client';

import { XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useDownloadJob } from '@/features/models/hooks/use-download-job';
import { cn } from '@/lib/utils';

function formatBytes(bytes: number | null): string {
  if (bytes === null) return '';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export type DownloadProgressProps = {
  jobId: string | null;
  /** Alias of the model being pulled, so the bar says what it belongs to. */
  modelAlias?: string;
  /** Offered once the job reaches a terminal state. */
  onDismiss?: () => void;
  className?: string;
};

export function DownloadProgress({
  jobId,
  modelAlias,
  onDismiss,
  className,
}: DownloadProgressProps) {
  const { data, error } = useDownloadJob(jobId);

  if (!jobId) return null;
  if (error) {
    return (
      <div className={cn('flex items-center gap-2', className)}>
        <p className="text-xs text-destructive">
          Progress unavailable — the job could not be read. The download itself
          runs on the server and is unaffected.
        </p>
        {onDismiss ? (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Dismiss"
            onClick={onDismiss}
          >
            <XIcon />
          </Button>
        ) : null}
      </div>
    );
  }
  if (!data) {
    return (
      <div className={cn('h-1.5 w-full animate-pulse rounded bg-muted', className)} />
    );
  }

  const percent =
    data.progress === null ? null : Math.round(data.progress * 100);
  const done = data.state === 'succeeded' || data.state === 'failed';
  const subject = modelAlias ?? 'model';

  return (
    <div className={cn('space-y-1', className)}>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent ?? undefined}
        aria-label={`Downloading ${subject}`}
        className="h-1.5 w-full overflow-hidden rounded bg-muted"
      >
        <div
          className={cn(
            'h-full rounded transition-[width]',
            data.state === 'failed' ? 'bg-destructive' : 'bg-primary',
            percent === null && !done && 'animate-pulse',
          )}
          style={{ width: `${done ? 100 : (percent ?? 100)}%` }}
        />
      </div>
      <div className="flex items-center gap-2">
        {/* A terminal job says so. The bar used to stop moving and stay on
            screen at whatever it had reached, which reads the same as a stalled
            download, and nothing ever removed it. */}
        <p
          aria-live="polite"
          className={cn(
            'text-xs',
            data.state === 'failed'
              ? 'text-destructive'
              : 'text-muted-foreground',
          )}
        >
          {data.state === 'succeeded'
            ? `Downloaded ${subject}.`
            : data.state === 'failed'
              ? `Download of ${subject} failed.`
              : `Downloading ${subject} — ${percent === null ? 'starting' : `${percent}%`}`}
          {!done && data.bytes_total
            ? ` - ${formatBytes(data.bytes_downloaded)} of ${formatBytes(data.bytes_total)}`
            : ''}
          {data.message ? ` ${data.message}` : ''}
        </p>
        {done && onDismiss ? (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Dismiss the download progress"
            onClick={onDismiss}
          >
            <XIcon />
          </Button>
        ) : null}
      </div>
    </div>
  );
}
