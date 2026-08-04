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
  useCheckNodeHealth,
  useDeleteNode,
  useNodes,
} from '@/features/nodes/hooks/use-nodes';
import { NodeFormDialog } from '@/features/nodes/components/node-form-dialog';
import { RUNTIME_LABELS, type Node } from '@/features/nodes/schema';

export function NodeTable() {
  const { can } = useSession();
  const mayWrite = can('node:write');
  const { data, isLoading, error, refetch } = useNodes();
  const check = useCheckNodeHealth();
  const remove = useDeleteNode();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Node | undefined>(undefined);
  const [deleting, setDeleting] = useState<Node | null>(null);

  const columns = useMemo<ColumnDef<Node>[]>(
    () => [
      {
        id: 'name',
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
      },
      {
        id: 'address',
        accessorKey: 'address',
        header: 'Address',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.original.address}
          </span>
        ),
      },
      {
        id: 'runtimes',
        accessorFn: (row) =>
          row.runtimes.map((runtime) => RUNTIME_LABELS[runtime]).join(', '),
        header: 'Runtimes',
      },
      {
        id: 'memory',
        accessorFn: (row) => row.total_memory_gb,
        header: 'Memory',
        cell: ({ row }) => `${row.original.total_memory_gb} GB`,
      },
      {
        id: 'status',
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        enableHiding: false,
        cell: ({ row }) => {
          const node = row.original;
          // Role gating here is a usability affordance only; the use case layer
          // authorises every one of these actions server-side.
          if (!mayWrite) return null;
          return (
            <div className="flex justify-end gap-1">
              <Button
                variant="outline"
                size="xs"
                disabled={check.isPending}
                onClick={() => check.mutate(node.id)}
              >
                Check
              </Button>
              <Button
                variant="ghost"
                size="xs"
                onClick={() => {
                  setEditing(node);
                  setFormOpen(true);
                }}
              >
                Edit
              </Button>
              <Button
                variant="ghost"
                size="xs"
                className="text-destructive"
                onClick={() => setDeleting(node)}
              >
                Remove
              </Button>
            </div>
          );
        },
      },
    ],
    [mayWrite, check],
  );

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        searchPlaceholder="Search nodes"
        emptyTitle="No nodes registered"
        emptyDescription="Register a compute node to attach models to it."
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
              Register node
            </Button>
          ) : null
        }
      />

      <NodeFormDialog
        key={editing?.id ?? 'create'}
        open={formOpen}
        onOpenChange={setFormOpen}
        node={editing}
      />

      <ConfirmDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={`Remove ${deleting?.name ?? 'this node'}?`}
        description="A node with models still registered to it cannot be removed; move or delete those models first."
        confirmLabel="Remove"
        destructive
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.id);
        }}
      />
    </>
  );
}
