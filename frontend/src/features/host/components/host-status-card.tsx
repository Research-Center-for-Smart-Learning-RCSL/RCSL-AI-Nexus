'use client';

import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Spinner } from '@/components/composed/spinner';
import { useHostStatus } from '@/features/host/hooks/use-host';
import { formatUptime } from '@/features/host/schema';

/**
 * What the Mac has left, on the screen about the machine it describes.
 *
 * The question this answers is "is there room", not "how is it performing".
 * There is no GPU utilisation and no temperature here, and that is a scope
 * decision rather than an omission: `powermetrics` needs root, and running a
 * launchd job as root to draw a chart is a trade to make on purpose.
 */

function Figure({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: 'warn' | 'bad';
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          'font-heading text-lg font-semibold tabular-nums',
          tone === 'warn' && 'text-amber-600 dark:text-amber-500',
          tone === 'bad' && 'text-destructive',
        )}
      >
        {value}
      </p>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function gb(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(1)} GB`;
}

export function HostStatusCard() {
  const { data, isLoading, error } = useHostStatus();

  if (isLoading) return <Spinner label="Reading the host" />;

  // An error here is the request failing, not the agent being absent — the
  // endpoint answers 200 with `reporting: false` for that. Both end up saying
  // the same thing to the reader, which is the honest answer in either case:
  // this panel does not know.
  if (error || !data?.reporting) {
    return (
      <div className="rounded-lg border border-dashed p-4">
        <p className="text-sm font-medium">Host not reporting</p>
        <p className="max-w-prose text-xs text-muted-foreground">
          The launchd metrics agent is not answering. Containers on macOS cannot
          read the Mac&apos;s own memory or disk — they would report the Linux VM
          they run in — so these figures are blank rather than guessed. See
          <code className="mx-1">launchd/host-metrics.py</code>.
        </p>
      </div>
    );
  }

  const { memory, disk, system } = data;

  // Thresholds against the machine's own size rather than fixed numbers, so
  // this stays meaningful on a second node with different hardware.
  const memoryShare =
    memory.available_gb !== null && memory.total_gb ? memory.available_gb / memory.total_gb : null;
  const memoryTone =
    memoryShare === null ? undefined : memoryShare < 0.1 ? 'bad' : memoryShare < 0.2 ? 'warn' : undefined;
  const diskShare = disk.free_gb !== null && disk.total_gb ? disk.free_gb / disk.total_gb : null;
  const diskTone =
    diskShare === null ? undefined : diskShare < 0.05 ? 'bad' : diskShare < 0.15 ? 'warn' : undefined;
  // Any swap in use is worth saying on a machine whose purpose is holding
  // weights in memory: it means the budget has already been overspent.
  const swapping = (memory.swap_used_gb ?? 0) > 0.1;

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-heading text-sm font-semibold">Compute host</h2>
        <div className="flex items-center gap-2">
          {swapping ? <Badge variant="outline">swapping</Badge> : null}
          <Badge variant="outline">up {formatUptime(system.uptime_seconds)}</Badge>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Figure
          label="Memory available"
          value={gb(memory.available_gb)}
          hint={memory.total_gb ? `of ${gb(memory.total_gb)} unified` : undefined}
          tone={memoryTone}
        />
        <Figure
          label="Disk free"
          value={gb(disk.free_gb)}
          hint={disk.total_gb ? `of ${gb(disk.total_gb)} on ${disk.volume ?? '/'}` : undefined}
          tone={diskTone}
        />
        <Figure
          label="Swap in use"
          value={gb(memory.swap_used_gb)}
          hint={swapping ? 'weights are being paged out' : 'nothing paged out'}
          tone={swapping ? 'warn' : undefined}
        />
        <Figure
          label="Load"
          value={system.load_1m === null ? '—' : system.load_1m.toFixed(2)}
          hint={
            system.cpu_count
              ? `${system.load_5m ?? '—'} / ${system.load_15m ?? '—'} over ${system.cpu_count} cores`
              : undefined
          }
        />
      </div>

      <p className="text-xs text-muted-foreground">
        Read from the Mac itself by a launchd agent, not from inside a container:
        a container here would describe the Linux VM it runs in. The memory
        budget that governs model loads still uses the configured 64 GB rather
        than this figure.
      </p>
    </div>
  );
}
