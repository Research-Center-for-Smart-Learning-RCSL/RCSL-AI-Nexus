'use client';

import { useEffect, useState } from 'react';
import { PlusIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/composed/data-table';
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
import type { Model } from '@/features/models/schema';
import { useModelColumns } from './model-columns';

/** Per-tab, so two tabs pulling different models do not overwrite each other. */
const DOWNLOAD_JOB_KEY = 'nexus.models.download-job';

export function ModelTable() {
  const { can } = useSession();
  const mayWrite = can('model:write');
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

  // An unreadable job is not worth restoring next time. The banner stays until
  // dismissed so the failure is not silent, but the id leaves storage now
  // rather than greeting the next visit to this screen.
  const jobFailedToLoad = job.isError;
  useEffect(() => {
    if (jobFailedToLoad) sessionStorage.removeItem(DOWNLOAD_JOB_KEY);
  }, [jobFailedToLoad]);

  // Which model the bar is about, resolved from the job rather than remembered
  // separately, so it survives the reload above.
  const jobAlias = data?.find((model) => model.id === job.data?.model_id)?.alias;

  const columns = useModelColumns({ mayWrite, load, unload, download, trackJob, setEditing, setFormOpen, setDeleting });

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
          mayWrite ? (
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
        description="Refused while a routing policy still binds this alias, and refused while the model is loaded or mid-transfer — repoint the policy and unload it first. The downloaded weights are not deleted."
        confirmLabel="Remove"
        destructive
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.id);
        }}
      />
    </>
  );
}
