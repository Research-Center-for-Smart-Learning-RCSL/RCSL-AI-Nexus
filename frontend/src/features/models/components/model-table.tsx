'use client';

import { useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { PlusIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/composed/data-table';
import { StatusBadge } from '@/components/composed/status-badge';
import { ConfirmDialog } from '@/components/composed/confirm-dialog';
import { useSession } from '@/lib/session';
import {
  useDeleteModel,
  useInvalidateModels,
  useLoadModel,
  useModels,
  useNodes,
  useStartDownload,
  useUnloadModel,
} from '@/features/models/hooks/use-models';
import { useDownloadJob } from '@/features/models/hooks/use-download-job';
import { DownloadProgress } from '@/features/models/components/download-progress';
import { ModelFormDialog } from '@/features/models/components/model-form-dialog';
import { RUNTIME_LABELS, type Model } from '@/features/models/schema';

/** Per-tab, so two tabs pulling different models do not overwrite each other. */
const DOWNLOAD_JOB_KEY = 'nexus.models.download-job';

export function ModelTable() {
  const { isAdmin } = useSession();
  const { data, isLoading, error, refetch } = useModels();
  const nodes = useNodes();
  const load = useLoadModel();
  const unload = useUnloadModel();
  const remove = useDeleteModel();
  const download = useStartDownload();
  const invalidateModels = useInvalidateModels();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Model | undefined>(undefined);
  const [deleting, setDeleting] = useState<Model | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // The download outlives the page: it runs on the server, and a pull of tens
  // of gigabytes is exactly the thing somebody reloads or navigates away from
  // while it works. Held in sessionStorage rather than component state alone,
  // so coming back shows the progress instead of a row stuck on `downloading`
  // with nothing to explain it. Per-tab, because it is a view preference and
  // not a fact about the deployment.
  useEffect(() => {
    const stored = sessionStorage.getItem(DOWNLOAD_JOB_KEY);
    if (stored) setActiveJobId(stored);
  }, []);

  function trackJob(jobId: string | null) {
    setActiveJobId(jobId);
    if (jobId) sessionStorage.setItem(DOWNLOAD_JOB_KEY, jobId);
    else sessionStorage.removeItem(DOWNLOAD_JOB_KEY);
  }

  // The job is owned here rather than inside DownloadProgress, which only
  // renders: the table is what has to refresh when the pull finishes, and
  // useDownloadJob stops polling at a terminal state without telling anyone.
  // Without this the row sits at `downloading` until the page is reloaded.
  const job = useDownloadJob(activeJobId);
  const jobState = job.data?.state;
  useEffect(() => {
    if (jobState === 'succeeded' || jobState === 'failed') {
      void invalidateModels();
    }
  }, [jobState, invalidateModels]);

  // Which model the bar is about, resolved from the job rather than remembered
  // separately, so it survives the reload above.
  const jobAlias = data?.find((model) => model.id === job.data?.model_id)?.alias;

  const columns = useMemo<ColumnDef<Model>[]>(
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
          // Role gating here is a usability affordance only. The use case layer
          // authorises every one of these actions server-side.
          if (!isAdmin) return null;
          return (
            <div className="flex justify-end gap-1">
              {/* The offered actions mirror the use cases' own preconditions,
                  so a button that is present is a button that can succeed.
                  Download is refused only for a loaded model (unload first)
                  and the transient states; Load requires `downloaded`, and
                  offering it on `not_downloaded` — as this table did until
                  2026-07-26 — guarantees a 409 and leaves a freshly
                  registered model with no way forward at all. */}
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
              {model.state === 'loaded' && (
                <Button
                  variant="outline"
                  size="xs"
                  disabled={busy || unload.isPending}
                  onClick={() => unload.mutate(model.id)}
                >
                  Unload
                </Button>
              )}
              {model.state === 'downloaded' && (
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
    [isAdmin, load, unload, download],
  );

  return (
    <>
      {activeJobId && (
        <DownloadProgress
          jobId={activeJobId}
          modelAlias={jobAlias}
          onDismiss={() => trackJob(null)}
          className="mb-3"
        />
      )}

      <DataTable
        columns={columns}
        data={data}
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        searchPlaceholder="Search models"
        emptyTitle="No models registered"
        emptyDescription="Register a model to make it available to routing policies."
        getRowId={(row) => row.id}
        toolbar={
          isAdmin ? (
            <Button
              size="sm"
              onClick={() => {
                setEditing(undefined);
                setFormOpen(true);
              }}
            >
              <PlusIcon />
              Register model
            </Button>
          ) : null
        }
      />

      <ModelFormDialog
        key={editing?.id ?? 'create'}
        open={formOpen}
        onOpenChange={setFormOpen}
        model={editing}
        // Falls back to a free-text identifier if the list has not arrived,
        // which is what the dialog does with an empty array.
        nodes={nodes.data ?? []}
      />

      <ConfirmDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={`Remove ${deleting?.alias ?? 'this model'}?`}
        description="Routing policies that reference this alias will stop resolving. The downloaded weights are not deleted."
        confirmLabel="Remove"
        destructive
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.id);
        }}
      />
    </>
  );
}
