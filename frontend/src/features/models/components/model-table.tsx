'use client';

import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { PlusIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/composed/data-table';
import { StatusBadge } from '@/components/composed/status-badge';
import { ConfirmDialog } from '@/components/composed/confirm-dialog';
import { useSession } from '@/lib/session';
import {
  useDeleteModel,
  useLoadModel,
  useModels,
  useNodes,
  useUnloadModel,
} from '@/features/models/hooks/use-models';
import { ModelFormDialog } from '@/features/models/components/model-form-dialog';
import { RUNTIME_LABELS, type Model } from '@/features/models/schema';

export function ModelTable() {
  const { isAdmin } = useSession();
  const { data, isLoading, error, refetch } = useModels();
  const nodes = useNodes();
  const load = useLoadModel();
  const unload = useUnloadModel();
  const remove = useDeleteModel();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Model | undefined>(undefined);
  const [deleting, setDeleting] = useState<Model | null>(null);

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
        cell: ({ row }) => `${row.original.resource_profile.memory_gb} GB`,
      },
      {
        id: 'state',
        accessorKey: 'state',
        header: 'State',
        cell: ({ row }) => <StatusBadge status={row.original.state} />,
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
              {model.state === 'loaded' ? (
                <Button
                  variant="outline"
                  size="xs"
                  disabled={busy || unload.isPending}
                  onClick={() => unload.mutate(model.id)}
                >
                  Unload
                </Button>
              ) : (
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
    [isAdmin, load, unload],
  );

  return (
    <>
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
