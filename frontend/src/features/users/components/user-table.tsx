'use client';

import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { PlusIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable } from '@/components/composed/data-table';
import { ConfirmDialog } from '@/components/composed/confirm-dialog';
import { DisabledReason } from '@/components/composed/disabled-reason';
import { OneTimeSecret } from '@/components/composed/one-time-secret';
import { SecretDialog } from '@/components/composed/secret-dialog';
import {
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useSession } from '@/lib/session';
import {
  useDeleteUser,
  useIssueInvitation,
  useIssuePasswordReset,
  useUsers,
} from '@/features/users/hooks/use-users';
import { InviteUserDialog } from '@/features/users/components/invite-user-dialog';
import { EditUserDialog } from '@/features/users/components/edit-user-dialog';
import { ROLE_LABELS, type User } from '@/features/users/schema';

export function UserTable() {
  const { can, me } = useSession();
  // `user:write` rather than "is an administrator": `tenant_admin` holds it
  // for its own tenant, and `auditor` and `operator` may read this table
  // without being offered actions the server will refuse.
  const mayWrite = can('user:write');
  const { data, isLoading, error, refetch } = useUsers();
  const remove = useDeleteUser();
  const reinvite = useIssueInvitation();
  const reset = useIssuePasswordReset();

  const [inviteOpen, setInviteOpen] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);
  const [linkAcknowledged, setLinkAcknowledged] = useState(false);
  const [issuedLink, setIssuedLink] = useState<{
    title: string;
    url: string;
  } | null>(null);

  const columns = useMemo<ColumnDef<User>[]>(
    () => [
      {
        id: 'login',
        accessorKey: 'login',
        header: 'Login',
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.display_name}</div>
            <div className="text-xs text-muted-foreground">
              {row.original.login}
            </div>
          </div>
        ),
      },
      {
        id: 'role',
        accessorKey: 'role',
        header: 'Role',
        cell: ({ row }) => ROLE_LABELS[row.original.role],
      },
      {
        id: 'credentials',
        header: 'Entrances',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex gap-1">
            {row.original.tailscale_login ? (
              <Badge variant="outline">Tailnet</Badge>
            ) : null}
            {row.original.has_local_credentials ? (
              <Badge variant="outline">
                Public{row.original.has_totp ? ' + TOTP' : ''}
              </Badge>
            ) : null}
            {!row.original.tailscale_login &&
            !row.original.has_local_credentials ? (
              <Badge variant="secondary">Invited, not accepted</Badge>
            ) : null}
          </div>
        ),
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        enableHiding: false,
        cell: ({ row }) => {
          const user = row.original;
          if (!mayWrite) return null;
          return (
            <div className="flex justify-end gap-1">
              <Button
                variant="ghost"
                size="xs"
                onClick={() => setEditing(user)}
              >
                Edit
              </Button>
              <Button
                variant="ghost"
                size="xs"
                disabled={reinvite.isPending}
                onClick={async () => {
                  const invitation = await reinvite.mutateAsync(user.id);
                  if (invitation.url) {
                    setIssuedLink({
                      title: 'Single-use invitation link',
                      url: invitation.url,
                    });
                  }
                }}
              >
                Re-invite
              </Button>
              {/* A disabled button with no explanation reads as a fault in the
                  page. Both of these are off for a reason specific to the row,
                  and the reason has to live on a wrapper: see DisabledReason. */}
              <DisabledReason
                reason={
                  user.has_local_credentials
                    ? undefined
                    : 'This account has no password. It signs in over the tailnet, where identity comes with the connection.'
                }
              >
                <Button
                  variant="ghost"
                  size="xs"
                  disabled={reset.isPending || !user.has_local_credentials}
                  onClick={async () => {
                    const issued = await reset.mutateAsync(user.id);
                    if (issued.url) {
                      setIssuedLink({
                        title: 'Single-use password reset link',
                        url: issued.url,
                      });
                    }
                  }}
                >
                  Reset password
                </Button>
              </DisabledReason>
              <DisabledReason
                reason={
                  user.id === me?.id
                    ? 'You cannot remove your own account. Another administrator has to do it.'
                    : undefined
                }
              >
                <Button
                  variant="ghost"
                  size="xs"
                  className="text-destructive"
                  disabled={user.id === me?.id}
                  onClick={() => setDeleting(user)}
                >
                  Remove
                </Button>
              </DisabledReason>
            </div>
          );
        },
      },
    ],
    [mayWrite, me, reinvite, reset],
  );

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        searchPlaceholder="Search users"
        emptyTitle="No users yet"
        emptyDescription="Invite someone to give them access to the management UI."
        getRowId={(row) => row.id}
        toolbar={
          mayWrite ? (
            <Button size="sm" onClick={() => setInviteOpen(true)}>
              <PlusIcon />
              Invite user
            </Button>
          ) : null
        }
      />

      <InviteUserDialog open={inviteOpen} onOpenChange={setInviteOpen} />

      {/* Mounted only while a row is selected, so the dialog's form defaults
          and its `useUpdateUser(id)` both belong to that row. Keeping it
          mounted and swapping the prop leaves both pointing at whoever was
          edited first. */}
      {editing ? (
        <EditUserDialog
          user={editing}
          isSelf={editing.id === me?.id}
          onClose={() => setEditing(null)}
        />
      ) : null}

      <SecretDialog
        open={Boolean(issuedLink)}
        // The acknowledgement here used to be decorative: the checkbox had no
        // handler and no gated control, so the link could be dismissed with
        // Escape and lost.
        locked={Boolean(issuedLink) && !linkAcknowledged}
        onOpenChange={(open) => {
          if (!open) {
            setIssuedLink(null);
            setLinkAcknowledged(false);
          }
        }}
        className="sm:max-w-lg"
      >
        <>
          <DialogHeader>
            <DialogTitle>{issuedLink?.title}</DialogTitle>
          </DialogHeader>
          {issuedLink ? (
            <OneTimeSecret
              title="Deliver this out of band"
              description="Single use, expires, and is not shown again."
              values={[issuedLink.url]}
              acknowledgement="I have copied this link"
              onAcknowledgedChange={setLinkAcknowledged}
            />
          ) : null}
          <DialogFooter>
            <Button
              disabled={!linkAcknowledged}
              onClick={() => {
                setIssuedLink(null);
                setLinkAcknowledged(false);
              }}
            >
              Done
            </Button>
          </DialogFooter>
        </>
      </SecretDialog>

      <ConfirmDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={`Remove ${deleting?.display_name ?? 'this user'}?`}
        description="Their sessions end immediately and any API keys they own should be revoked separately."
        confirmLabel="Remove"
        destructive
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.id);
        }}
      />
    </>
  );
}
