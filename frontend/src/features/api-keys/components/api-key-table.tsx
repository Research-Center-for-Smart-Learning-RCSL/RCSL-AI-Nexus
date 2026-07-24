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
  useApiKeys,
  useRevokeApiKey,
} from '@/features/api-keys/hooks/use-api-keys';
import { CreateApiKeyDialog } from '@/features/api-keys/components/create-api-key-dialog';
import { keyStatus, type ApiKey } from '@/features/api-keys/schema';

function formatDate(value: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleDateString();
}

export function ApiKeyTable() {
  const { me, isAdmin } = useSession();
  const { data, isLoading, error, refetch } = useApiKeys();
  const revoke = useRevokeApiKey();

  const [createOpen, setCreateOpen] = useState(false);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  const columns = useMemo<ColumnDef<ApiKey>[]>(
    () => [
      {
        id: 'name',
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.name}</div>
            {/* key_id is a separate random handle, not a slice of the secret. */}
            <div className="font-mono text-xs text-muted-foreground">
              {row.original.key_id}
            </div>
          </div>
        ),
      },
      {
        id: 'scopes',
        accessorFn: (row) => row.scopes.join(', '),
        header: 'Scopes',
      },
      {
        id: 'limits',
        header: 'Limits',
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {row.original.rate_limit_rpm} rpm,{' '}
            {row.original.quota_tokens_per_day.toLocaleString()} tokens/day
          </span>
        ),
      },
      {
        id: 'cidrs',
        accessorFn: (row) =>
          row.allowed_cidrs.length ? row.allowed_cidrs.join(', ') : 'any',
        header: 'Sources',
      },
      {
        id: 'owner',
        accessorFn: (row) => row.owner_display ?? row.owner_id,
        header: 'Owner',
      },
      {
        id: 'expires_at',
        accessorKey: 'expires_at',
        header: 'Expires',
        cell: ({ row }) => formatDate(row.original.expires_at),
      },
      {
        id: 'status',
        accessorFn: (row) => keyStatus(row),
        header: 'Status',
        cell: ({ row }) => <StatusBadge status={keyStatus(row.original)} />,
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        enableHiding: false,
        cell: ({ row }) => {
          const key = row.original;
          if (!isAdmin || key.revoked_at) return null;
          return (
            <div className="flex justify-end">
              <Button
                variant="ghost"
                size="xs"
                className="text-destructive"
                onClick={() => setRevoking(key)}
              >
                Revoke
              </Button>
            </div>
          );
        },
      },
    ],
    [isAdmin],
  );

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        searchPlaceholder="Search keys"
        emptyTitle="No API keys"
        emptyDescription="Issue a key to let an application reach the gateway."
        getRowId={(row) => row.key_id}
        toolbar={
          isAdmin ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <PlusIcon />
              Issue key
            </Button>
          ) : null
        }
      />

      <CreateApiKeyDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        ownerId={me?.id ?? ''}
      />

      <ConfirmDialog
        open={Boolean(revoking)}
        onOpenChange={(open) => {
          if (!open) setRevoking(null);
        }}
        title={`Revoke ${revoking?.name ?? 'this key'}?`}
        description="Revocation takes effect immediately. Anything using this key starts failing at once."
        confirmLabel="Revoke"
        destructive
        onConfirm={async () => {
          if (revoking) await revoke.mutateAsync(revoking.key_id);
        }}
      />
    </>
  );
}
