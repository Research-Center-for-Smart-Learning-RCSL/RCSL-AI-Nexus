'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';

import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/composed/status-badge';
import { useSetDebugWindow } from '@/features/api-keys/hooks/use-api-keys';
import { canManageKey, keyStatus, type ApiKey } from '@/features/api-keys/schema';

function formatDate(value: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleDateString();
}

function debugMinutesLeft(key: ApiKey): number {
  if (!key.debug_logging_until) return 0;
  const ms = new Date(key.debug_logging_until).getTime() - Date.now();
  return ms > 0 ? Math.ceil(ms / 60_000) : 0;
}

type Params = {
  viewer: { id: string | null; mayWriteAny: boolean; mayWriteOwn: boolean };
  debug: ReturnType<typeof useSetDebugWindow>;
  setEditing: (key: ApiKey) => void;
  setRevoking: (key: ApiKey) => void;
};

export function useApiKeyColumns(params: Params): ColumnDef<ApiKey>[] {
  const { viewer, debug, setEditing, setRevoking } = params;
  return useMemo<ColumnDef<ApiKey>[]>(
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
        header: 'Capabilities',
        // The default rides in this cell rather than in a column of its own.
        // It is null on almost every key, so a column would be mostly empty
        // while costing width on a table that already has eight — and where it
        // belongs is beside the list it has to be drawn from.
        cell: ({ row }) => (
          <div>
            {row.original.scopes.join(', ')}
            {row.original.default_capability ? (
              <div className="text-xs text-muted-foreground">
                anything else → {row.original.default_capability}
              </div>
            ) : null}
          </div>
        ),
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
          const debugLeft = debugMinutesLeft(key);
  return (
            <div className="flex justify-end gap-1">
              {/* One click, one hour; clicking an open window closes it. The
                  label carries the remaining time so an open window is visible
                  from the table rather than only from its effect: while it is
                  open, error responses to this key include operator detail. */}
              <Button
                variant="ghost"
                size="xs"
                className={debugLeft ? 'text-amber-600 dark:text-amber-500' : undefined}
                onClick={() =>
                  debug.mutate({ keyId: key.key_id, minutes: debugLeft ? 0 : 60 })
                }
              >
                {debugLeft ? `Debug ${debugLeft}m` : 'Debug'}
              </Button>
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
    [viewer, debug, setEditing, setRevoking],
  );
}
