'use client';

import { useState } from 'react';
import { PlusIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/composed/data-table';
import { ConfirmDialog } from '@/components/composed/confirm-dialog';
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
  useSetUserDebugWindow,
  useUsers,
} from '@/features/users/hooks/use-users';
import { InviteUserDialog } from '@/features/users/components/invite-user-dialog';
import { EditUserDialog } from '@/features/users/components/edit-user-dialog';
import type { User } from '@/features/users/schema';
import { useUserColumns } from './user-columns';

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
  const debug = useSetUserDebugWindow();

  const [inviteOpen, setInviteOpen] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);
  const [linkAcknowledged, setLinkAcknowledged] = useState(false);
  const [issuedLink, setIssuedLink] = useState<{
    title: string;
    url: string;
  } | null>(null);

  const columns = useUserColumns({ mayWrite, meId: me?.id ?? null, reinvite, reset, debug, setEditing, setDeleting, setIssuedLink });

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        searchPlaceholder="Search users"
        emptyTitle="No users"
        emptyDescription="Issue an invitation to grant access to the management UI."
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
        description="Their sessions end immediately, and the API keys they own are deleted with the account, so anything using one stops working at once. The audit log keeps what the account did."
        confirmLabel="Remove"
        destructive
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.id);
        }}
      />
    </>
  );
}
