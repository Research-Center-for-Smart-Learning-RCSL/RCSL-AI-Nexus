'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DisabledReason } from '@/components/composed/disabled-reason';
import { useIssueInvitation, useIssuePasswordReset, useSetUserDebugWindow } from '@/features/users/hooks/use-users';
import { ROLE_LABELS, type User } from '@/features/users/schema';

function debugMinutesLeft(user: User): number {
  if (!user.debug_logging_until) return 0;
  const ms = new Date(user.debug_logging_until).getTime() - Date.now();
  return ms > 0 ? Math.ceil(ms / 60_000) : 0;
}

type Params = {
  mayWrite: boolean;
  meId: string | null;
  reinvite: ReturnType<typeof useIssueInvitation>;
  reset: ReturnType<typeof useIssuePasswordReset>;
  debug: ReturnType<typeof useSetUserDebugWindow>;
  setEditing: (user: User) => void;
  setDeleting: (user: User) => void;
  setIssuedLink: (link: { title: string; url: string }) => void;
};

export function useUserColumns(params: Params): ColumnDef<User>[] {
  const { mayWrite, meId, reinvite, reset, debug, setEditing, setDeleting, setIssuedLink } = params;
  return useMemo<ColumnDef<User>[]>(
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
          const debugLeft = debugMinutesLeft(user);
  return (
            <div className="flex justify-end gap-1">
              {/* Same control as on the API keys table, on the credential this
                  screen is reached with. One click, one hour; clicking an open
                  window closes it, and the label carries the remaining time so
                  that a window left open is visible here rather than only in
                  the error bodies it widens. */}
              <Button
                variant="ghost"
                size="xs"
                className={
                  debugLeft ? 'text-amber-600 dark:text-amber-500' : undefined
                }
                onClick={() =>
                  debug.mutate({ userId: user.id, minutes: debugLeft ? 0 : 60 })
                }
              >
                {debugLeft ? `Debug ${debugLeft}m` : 'Debug'}
              </Button>
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
                  user.id === meId
                    ? 'You cannot remove your own account. Another administrator has to do it.'
                    : undefined
                }
              >
                <Button
                  variant="ghost"
                  size="xs"
                  className="text-destructive"
                  disabled={user.id === meId}
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
    [mayWrite, meId, reinvite, reset, debug, setEditing, setDeleting, setIssuedLink],
  );
}
