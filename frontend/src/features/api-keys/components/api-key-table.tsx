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
import { EditApiKeyDialog } from '@/features/api-keys/components/edit-api-key-dialog';
import { canManageKey, keyStatus, type ApiKey } from '@/features/api-keys/schema';
import { useAssistantSurface } from '@/features/assistant/context';

function formatDate(value: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleDateString();
}

export function ApiKeyTable() {
  const { me, isAdmin } = useSession();
  // No draft and nothing to apply: there is no form here. The surface alone is
  // what the assistant needs, so a question about rotating or revoking a key is
  // answered in the context of the screen asking it. A dialog opened from this
  // table registers over the top and hands the surface back when it closes.
  useAssistantSurface({ surface: 'api_keys.list' });
  const { data, isLoading, error, refetch } = useApiKeys();
  const revoke = useRevokeApiKey();

  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ApiKey | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  /**
   * What the caller may act on, matching the scopes the backend actually
   * grants. A member holds `api_key:write_own` (security.md §5.2 grants them
   * their own keys and nothing else), so gating every action on `isAdmin`
   * offered them a page that could only ever be empty and read-only while the
   * API would have accepted the request.
   */
  const viewer = useMemo(
    () => ({ id: me?.id ?? null, isAdmin }),
    [me?.id, isAdmin],
  );

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
          // A revoked key is final, not editable: the backend refuses an edit
          // on one, because the result would read as active in this table and
          // not be. Reissue instead.
          if (key.revoked_at || !canManageKey(key, viewer)) return null;
          return (
            <div className="flex justify-end gap-1">
              <Button variant="ghost" size="xs" onClick={() => setEditing(key)}>
                Edit
              </Button>
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
    [viewer],
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
          // Anyone signed in may issue a key for themselves. Gated on the id
          // rather than the role, because the dialog issues to `me.id` and
          // without one the request carries an empty owner.
          me?.id ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <PlusIcon />
              Issue key
            </Button>
          ) : null
        }
      />

      {me?.id ? (
        <CreateApiKeyDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          ownerId={me.id}
        />
      ) : null}

      {/* Mounted only while a key is selected, and keyed by it: the form reads
          its defaults once, so a kept-alive instance would show stale values
          after a second Edit. */}
      {editing ? (
        <EditApiKeyDialog
          key={editing.key_id}
          apiKey={editing}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
        />
      ) : null}

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
