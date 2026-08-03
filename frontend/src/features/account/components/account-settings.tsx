'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/composed/empty-state';
import { Spinner } from '@/components/composed/spinner';
import { useSession } from '@/lib/session';
import { ChangePasswordForm } from '@/features/account/components/change-password-form';
import { TotpReenrolmentCard } from '@/features/account/components/totp-reenrolment-card';

/**
 * Your own credentials, and nothing else.
 *
 * Every endpoint behind this screen acts on the caller's own id and takes no
 * user identifier, so there is nothing here an administrator does differently.
 *
 * The tailnet branch is not a permission check but a statement of fact: that
 * entrance carries identity in a header and issues no session, and an account
 * that has only ever been reached that way has no password to change and no
 * local second factor to replace. The bootstrapped first administrator is one
 * of these. The shell already hides the link there; this covers the URL bar.
 */
export function AccountSettings() {
  const { me, status, authMode } = useSession();

  if (status === 'loading') {
    return (
      <div className="flex justify-center py-12">
        <Spinner label="Loading your account" />
      </div>
    );
  }

  if (!me) return null; // The shell is already redirecting.

  return (
    <div className="max-w-2xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{me.display_name}</CardTitle>
          <CardDescription>
            {me.login} — {me.role}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">Entrance: {authMode ?? 'unknown'}</Badge>
          <span className="text-sm text-muted-foreground">
            Your display name and role are set by an administrator.
          </span>
        </CardContent>
      </Card>

      {authMode === 'tailnet' ? (
        <EmptyState
          title="Nothing to manage from this entrance"
          description="Over the tailnet your identity arrives with the connection rather than from a password, so there is no local credential here to change. Sign in through the public entrance to manage one."
        />
      ) : (
        <>
          <ChangePasswordForm />
          <TotpReenrolmentCard />
        </>
      )}
    </div>
  );
}
