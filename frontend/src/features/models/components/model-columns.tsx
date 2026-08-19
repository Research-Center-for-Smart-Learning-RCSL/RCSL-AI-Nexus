'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';

import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/composed/status-badge';
import { useLoadModel, useStartDownload, useUnloadModel } from '@/features/models/hooks/use-models';
import { RUNTIME_LABELS, type Model } from '@/features/models/schema';

type Params = {
  mayWrite: boolean;
  load: ReturnType<typeof useLoadModel>;
  unload: ReturnType<typeof useUnloadModel>;
  download: ReturnType<typeof useStartDownload>;
  trackJob: (jobId: string | null) => void;
  setEditing: (model: Model) => void;
  setFormOpen: (open: boolean) => void;
  setDeleting: (model: Model) => void;
};

export function useModelColumns(params: Params): ColumnDef<Model>[] {
  const { mayWrite, load, unload, download, trackJob, setEditing, setFormOpen, setDeleting } = params;
  return useMemo<ColumnDef<Model>[]>(
    () => [
      {
        id: 'alias',
        accessorKey: 'alias',
        header: 'Alias',
        cell: ({ row }) => (
          <span className="font-medium">{row.original.alias}</span>
        ),
      },
      {
        id: 'ref',
        accessorKey: 'ref',
        header: 'Reference',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.original.ref}
          </span>
        ),
      },
      {
        id: 'runtime',
        accessorKey: 'runtime',
        header: 'Runtime',
        cell: ({ row }) => RUNTIME_LABELS[row.original.runtime],
      },
      {
        id: 'capabilities',
        accessorFn: (row) => row.capabilities.join(', '),
        header: 'Capabilities',
      },
      {
        id: 'memory',
        accessorFn: (row) => row.resource_profile.memory_gb,
        header: 'Memory',
        cell: ({ row }) => {
          const declared = row.original.resource_profile.memory_gb;
          const observed = row.original.observed_memory_gb;
          // The runtime's own figure includes the KV cache the declared one
          // does not, and it is what the memory budget now counts.
          if (observed == null) return `${declared} GB`;
          return `${declared} GB (resident ${observed.toFixed(1)} GB)`;
        },
      },
      {
        id: 'state',
        accessorKey: 'state',
        header: 'State',
        cell: ({ row }) => {
          const { state, observed_state } = row.original;
  return (
            <div className="flex flex-col gap-0.5">
              <StatusBadge status={state} />
              {/* Shown only when the runtime contradicts the registry: that
                  divergence is what routing now follows, so it must not be
                  invisible. Agreement and "not observed" both stay quiet. */}
              {observed_state !== null && observed_state !== state && (
                <span className="text-xs text-destructive">
                  runtime reports {observed_state.replace(/_/g, ' ')}
                </span>
              )}
            </div>
          );
        },
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        enableHiding: false,
        cell: ({ row }) => {
          const model = row.original;
          const busy =
            model.state === 'loading' ||
            model.state === 'unloading' ||
            model.state === 'downloading';
          // What `load` and `unload` decide on: the runtime's observation
          // outranks the registry's intent, exactly as `ManageModels` and
          // `RoutingService._satisfies` do. `download` is deliberately not on
          // this, because it reads the registry's own state.
          const effective = model.observed_state ?? model.state;
          // Role gating here is a usability affordance only. The use case layer
          // authorises every one of these actions server-side.
          if (!mayWrite) return null;
          return (
            <div className="flex justify-end gap-1">
              {/* The offered actions mirror the use cases' own preconditions,
                  so a button that is present is a button that can succeed —
                  which means reading the same field each use case reads, and
                  they do not all read the same one. Load and Unload go on
                  `observed_state or state`: a model the runtime has evicted
                  while the registry still records it as loaded is precisely
                  the case Load exists for, and gating on `state` alone hid it
                  there while offering Unload, which is the one action that
                  could not work. Download is refused only for a loaded model
                  (unload first) and the transient states, and it is about what
                  is on disk, so it stays on the registry's own state. Load
                  requires `downloaded`, and offering it on `not_downloaded` —
                  as this table did until 2026-07-26 — guarantees a 409 and
                  leaves a freshly registered model with no way forward at
                  all. */}
              {model.state !== 'loaded' && (
                <Button
                  variant="outline"
                  size="xs"
                  disabled={busy || download.isPending}
                  onClick={() =>
                    download.mutate(model.id, {
                      onSuccess: (started) => trackJob(started.job_id),
                    })
                  }
                >
                  {model.state === 'downloaded' ? 'Re-download' : 'Download'}
                </Button>
              )}
              {effective === 'loaded' && (
                <Button
                  variant="outline"
                  size="xs"
                  disabled={busy || unload.isPending}
                  onClick={() => unload.mutate(model.id)}
                >
                  Unload
                </Button>
              )}
              {effective === 'downloaded' && (
                <Button
                  variant="outline"
                  size="xs"
                  disabled={busy || load.isPending}
                  onClick={() => load.mutate(model.id)}
                >
                  Load
                </Button>
              )}
              <Button
                variant="ghost"
                size="xs"
                onClick={() => {
                  setEditing(model);
                  setFormOpen(true);
                }}
              >
                Edit
              </Button>
              <Button
                variant="ghost"
                size="xs"
                className="text-destructive"
                onClick={() => setDeleting(model)}
              >
                Remove
              </Button>
            </div>
          );
        },
      },
    ],
    [
      mayWrite,
      load,
      unload,
      download,
      trackJob,
      setEditing,
      setFormOpen,
      setDeleting,
    ],
  );
}
