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
  const { me, can } = useSession();
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
   * Revoked keys are hidden by default, and the toggle carries their count.
   *
   * Hiding them is the useful default: a revoked key is final — the backend
   * refuses to edit one — so it can never be anything but history, and a list
   * that is mostly history is one nobody scans for the row they came for. This
   * deployment reached seven keys of which six were single-use verification
   * keys revoked minutes after being issued.
   *
   * What stops that default from being a disappearance is the **count in the
   * label**. "Show 7 revoked" says both that they exist and where they went;
   * a bare "Show revoked" would leave someone hunting for a key they know they
   * created. The button is absent entirely when there are none, because a
   * control that filters nothing is a question the reader has to answer for no
   * reason.
   *
   * The search box filters again, after this, and an empty result there is the
   * table's own story to tell — `DataTable` says so rather than falling through
   * to the caller's "no keys yet" message, which would be a false statement
   * about a table whose rows the query merely did not match.
   *
   * Deliberately not persisted. The preference is worth a click, and a stored
   * one would outlive the situation that motivated it — the next visit is
   * usually about an active key.
   *
   * Expired keys are **not** covered by this. They are inert for a different
   * reason and become so without anyone acting; conflating the two would let
   * one control mean "hide what I revoked" and "hide what lapsed" at once, and
   * the second is often exactly what someone came to look for.
   */
  const [showRevoked, setShowRevoked] = useState(false);

  const revokedCount = useMemo(
    () => (data ?? []).filter((key) => key.revoked_at).length,
    [data],
  );
  const rows = useMemo(() => {
    if (showRevoked || !data) return data;
    return data.filter((key) => !key.revoked_at);
  }, [data, showRevoked]);
  const everythingIsRevoked = Boolean(data?.length) && rows?.length === 0;

  /**
   * What the caller may act on, matching the scopes the backend actually
   * grants. A member holds `api_key:write_own` (security.md §5.2 grants them
   * their own keys and nothing else), so gating every action on "is an
   * administrator" offered them a page that could only ever be empty and
   * read-only while the API would have accepted the request.
   *
   * The scope, not the role: `tenant_admin` holds `api_key:write_any` within
   * its tenant, and `operator` deliberately does not hold it at all.
   */
  const mayWriteAny = can('api_key:write_any');
  const mayWriteOwn = can('api_key:write_own');
  const viewer = useMemo(
    () => ({ id: me?.id ?? null, mayWriteAny, mayWriteOwn }),
    [me?.id, mayWriteAny, mayWriteOwn],
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
        data={rows}
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        searchPlaceholder="Search keys"
        emptyTitle={everythingIsRevoked ? 'No active keys' : 'No API keys'}
        emptyDescription={
          // Two different situations that look identical once the rows are
          // filtered out. Saying "issue a key" to someone whose keys are all
          // revoked answers a question they did not ask and hides the fact that
          // the screen is filtered at all.
          everythingIsRevoked
            ? `Every key here has been revoked. Use "Show ${revokedCount} revoked" above to see them.`
            : 'Issue a key to let an application reach the gateway.'
        }
        getRowId={(row) => row.key_id}
        toolbar={
          <>
            {/* No `aria-pressed`. The label already changes to name the action,
                and a toggle that does both announces "Hide 2 revoked, pressed"
                — the state twice, in opposite directions. One mechanism or the
                other; the label is the one that also works for someone who can
                see the button but not tell a pressed variant from an unpressed
                one. */}
            {revokedCount ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setShowRevoked((shown) => !shown)}
              >
                {showRevoked
                  ? `Hide ${revokedCount} revoked`
                  : `Show ${revokedCount} revoked`}
              </Button>
            ) : null}
            {/* Both conditions, and neither is redundant. `api_key:write_own`
                is what the endpoint requires, and it is not universal any more:
                `auditor` deliberately holds no write at all, so "anyone signed
                in may issue a key for themselves" stopped being true when that
                role arrived and this button would have offered a guaranteed
                403. The id is still needed because the dialog issues to
                `me.id`, and without one the request carries an empty owner. */}
            {me?.id && can('api_key:write_own') ? (
              <Button size="sm" onClick={() => setCreateOpen(true)}>
                <PlusIcon />
                Issue key
              </Button>
            ) : null}
          </>
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
