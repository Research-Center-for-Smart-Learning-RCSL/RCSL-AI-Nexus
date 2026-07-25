'use client';

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
  className?: string;
};

export function DownloadProgress({ jobId, className }: DownloadProgressProps) {
  const { data, error } = useDownloadJob(jobId);

  if (!jobId) return null;
  if (error) {
    return (
      <p className={cn('text-xs text-destructive', className)}>
        Progress unavailable.
      </p>
    );
  }
  if (!data) {
    return (
      <div className={cn('h-1.5 w-full animate-pulse rounded bg-muted', className)} />
    );
  }

  const percent =
    data.progress === null ? null : Math.round(data.progress * 100);

  return (
    <div className={cn('space-y-1', className)}>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent ?? undefined}
        className="h-1.5 w-full overflow-hidden rounded bg-muted"
      >
        <div
          className={cn(
            'h-full rounded transition-[width]',
            data.state === 'failed' ? 'bg-destructive' : 'bg-primary',
            percent === null && 'animate-pulse',
          )}
          style={{ width: `${percent ?? 100}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        {percent === null ? 'Starting' : `${percent}%`}
        {data.bytes_total
          ? ` - ${formatBytes(data.bytes_downloaded)} of ${formatBytes(data.bytes_total)}`
          : ''}
        {data.message ? ` - ${data.message}` : ''}
      </p>
    </div>
  );
}
