'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/composed/empty-state';
import { Spinner } from '@/components/composed/spinner';
import { useSession } from '@/lib/session';
import { ChangePasswordForm } from '@/features/account/components/change-password-form';
import { TotpReenrolmentCard } from '@/features/account/components/totp-reenrolment-card';
import { ScopeList } from '@/features/users/components/scope-list';
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/features/users/schema';

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

  // Sorted so the list reads the same on every visit; the server already sorts
  // it, and this makes the screen independent of that continuing to be true.
  const scopes = [...(me.scopes ?? [])].sort();

  return (
    <div className="max-w-2xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{me.display_name}</CardTitle>
          <CardDescription>
            {me.login} — {ROLE_LABELS[me.role] ?? me.role}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">Entrance: {authMode ?? 'unknown'}</Badge>
          <span className="text-sm text-muted-foreground">
            Your display name and role are set by an administrator.
          </span>
        </CardContent>
      </Card>

      {/* What this account can actually do, from `GET /admin/me` — the scopes
          the request was authorized with, not a description of the role name.
          Shown to everyone rather than only to administrators: "why can I not
          see the Logs screen" is a question the person without the scope asks,
          and the answer belongs where they can reach it. */}
      <Card>
        <CardHeader>
          <CardTitle>What you can do</CardTitle>
          <CardDescription>
            {ROLE_DESCRIPTIONS[me.role] ??
              'Your permissions are resolved from your role when each request arrives.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {scopes.length > 0 ? (
            <>
              <ScopeList scopes={scopes} />
              <p className="mt-3 text-xs text-muted-foreground">
                {scopes.length} permission{scopes.length === 1 ? '' : 's'}, from
                the role above. An administrator changes these by changing your
                role; they are not editable one by one.
              </p>
            </>
          ) : (
            // Distinguishes "holds nothing" from "we were not told", which look
            // identical as an empty list and mean opposite things.
            <p className="text-sm text-muted-foreground">
              This entrance did not report your permissions. That is a gap in
              what the server sent, not a statement that you have none.
            </p>
          )}
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
