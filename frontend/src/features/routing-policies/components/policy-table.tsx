'use client';

import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { PlusIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable } from '@/components/composed/data-table';
import { ConfirmDialog } from '@/components/composed/confirm-dialog';
import { useSession } from '@/lib/session';
import { capabilitySchema, type Capability } from '@/features/models/schema';
import { useModels } from '@/features/models/hooks/use-models';
import {
  useDeleteRoutingPolicy,
  useRoutingPolicies,
} from '@/features/routing-policies/hooks/use-routing-policies';
import { PolicyFormDialog } from '@/features/routing-policies/components/policy-form-dialog';
import type { RoutingPolicy } from '@/features/routing-policies/schema';

const ALL_CAPABILITIES = capabilitySchema.options;

/** "alias (p100)", highest priority first, matching how the gateway evaluates. */
function summariseCandidates(policy: RoutingPolicy): string {
  return [...policy.candidates]
    .sort((a, b) => b.priority - a.priority)
    .map((candidate) => `${candidate.model_alias} (p${candidate.priority})`)
    .join(', ');
}

export function PolicyTable() {
  const { can } = useSession();
  const mayWrite = can('routing:write');
  const { data, isLoading, error, refetch } = useRoutingPolicies();
  const models = useModels();
  const remove = useDeleteRoutingPolicy();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<RoutingPolicy | undefined>(undefined);
  const [deleting, setDeleting] = useState<RoutingPolicy | null>(null);

  const modelAliases = useMemo(
    () => Array.from(new Set((models.data ?? []).map((model) => model.alias))).sort(),
    [models.data],
  );

  // Creating is only offered for capabilities without a policy, since a save is
  // a full replacement keyed by capability and would silently overwrite one.
  const uncovered = useMemo<Capability[]>(() => {
    const covered = new Set((data ?? []).map((policy) => policy.capability));
    return ALL_CAPABILITIES.filter((capability) => !covered.has(capability));
  }, [data]);

  const columns = useMemo<ColumnDef<RoutingPolicy>[]>(
    () => [
      {
        id: 'capability',
        accessorKey: 'capability',
        header: 'Capability',
        cell: ({ row }) => (
          <Badge variant="outline" className="font-medium">
            {row.original.capability}
          </Badge>
        ),
      },
      {
        id: 'candidates',
        accessorFn: (row) => row.candidates.length,
        header: 'Candidates',
      },
      {
        id: 'summary',
        accessorFn: (row) => summariseCandidates(row),
        header: 'Order',
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {summariseCandidates(row.original)}
          </span>
        ),
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        enableHiding: false,
        cell: ({ row }) => {
          // Role gating here is a usability affordance only; the use case layer
          // authorises every action server-side.
          if (!mayWrite) return null;
          const policy = row.original;
          return (
            <div className="flex justify-end gap-1">
              <Button
                variant="ghost"
                size="xs"
                onClick={() => {
                  setEditing(policy);
                  setFormOpen(true);
                }}
              >
                Edit
              </Button>
              <Button
                variant="ghost"
                size="xs"
                className="text-destructive"
                onClick={() => setDeleting(policy)}
              >
                Remove
              </Button>
            </div>
          );
        },
      },
    ],
    [mayWrite],
  );

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        searchPlaceholder="Search policies"
        emptyTitle="No routing policies"
        emptyDescription="Without a policy, the gateway answers every request for that capability with 'no model available'."
        getRowId={(row) => row.capability}
        toolbar={
          mayWrite ? (
            <Button
              size="sm"
              disabled={uncovered.length === 0}
              onClick={() => {
                setEditing(undefined);
                setFormOpen(true);
              }}
            >
              <PlusIcon />
              Add policy
            </Button>
          ) : null
        }
      />

      {formOpen ? (
        <PolicyFormDialog
          key={editing?.capability ?? 'create'}
          open={formOpen}
          onOpenChange={setFormOpen}
          policy={editing}
          capabilityOptions={editing ? [editing.capability] : uncovered}
          modelAliases={modelAliases}
        />
      ) : null}

      <ConfirmDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={`Remove the ${deleting?.capability ?? ''} policy?`}
        description="The gateway will stop serving this capability until a new policy is written."
        confirmLabel="Remove"
        destructive
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.capability);
        }}
      />
    </>
  );
}
