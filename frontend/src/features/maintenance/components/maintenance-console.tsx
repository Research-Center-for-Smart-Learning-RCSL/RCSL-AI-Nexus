'use client';

import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ConfirmDialog } from '@/components/composed/confirm-dialog';
import { DisabledReason } from '@/components/composed/disabled-reason';
import { ErrorState, describeError } from '@/components/composed/error-state';
import { Spinner } from '@/components/composed/spinner';
import { toInstant, toLocalInput } from '@/features/refusals/time-range';

import {
  useEnterMaintenance,
  useMaintenanceAdmin,
  useReopenAfterMaintenance,
  useSetMaintenanceMessage,
} from '../hooks/use-maintenance-admin';
import { formatExpectedReturn } from '../format';

const MESSAGE_MAX = 500;

/**
 * Close and reopen the platform (#61), and edit what everyone else is shown.
 *
 * What closing does is stated in the confirmation rather than left to the
 * button's label, because it is immediate and reaches everybody: every account
 * but a platform administrator is signed out on the spot, and nobody,
 * administrators included, reaches a model until it reopens.
 */
export function MaintenanceConsole() {
  const query = useMaintenanceAdmin();
  const enter = useEnterMaintenance();
  const reopen = useReopenAfterMaintenance();
  const save = useSetMaintenanceMessage();

  const [message, setMessage] = useState('');
  const [returnAt, setReturnAt] = useState('');
  const [confirmEnter, setConfirmEnter] = useState(false);
  const [confirmReopen, setConfirmReopen] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);

  const state = query.data;
  // Seeded from the server once per revision, so an edit in progress is not
  // overwritten by the poll, and another administrator's save is picked up.
  const revision = state?.revision;
  useEffect(() => {
    if (!state) return;
    setMessage(state.message ?? '');
    setReturnAt(state.expected_return_at ? toLocalInput(new Date(state.expected_return_at)) : '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revision]);

  if (query.isPending) return <Spinner label="Loading maintenance state" />;
  if (query.isError || !state) {
    return <ErrorState title="Could not read the maintenance state" error={query.error} onRetry={() => void query.refetch()} />;
  }

  const notice = {
    message: message.trim() ? message.trim() : null,
    expected_return_at: returnAt ? (toInstant(returnAt) ?? null) : null,
  };
  const back = formatExpectedReturn(state.expected_return_at);
  const enterDisabled = !state.enabled
    ? 'Maintenance mode is not enabled on this deployment (MAINTENANCE_ENABLED).'
    : undefined;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{state.closed ? 'Closed for maintenance' : 'Open'}</CardTitle>
          <CardDescription>
            {state.closed
              ? 'Only platform administrators can sign in. No model serves anyone, administrators included, and every API key is refused with 503 maintenance until the platform reopens.'
              : 'Every entrance is serving normally.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {state.closed && state.changed_at ? (
            <p>
              Closed since {new Date(state.changed_at).toLocaleString()}
              {back ? `, expected back ${back}` : ''}.
            </p>
          ) : null}
          <p className="text-muted-foreground">
            Closing does not yet interrupt generations already running on the runtime,
            and does not release or restore resident models; those are still being built
            (#61).
          </p>
          <div className="flex flex-wrap gap-2 pt-2">
            {state.closed ? (
              <Button onClick={() => setConfirmReopen(true)}>Reopen the platform</Button>
            ) : (
              <DisabledReason reason={enterDisabled}>
                <Button
                  variant="destructive"
                  disabled={Boolean(enterDisabled)}
                  onClick={() => setConfirmEnter(true)}
                >
                  Close for maintenance
                </Button>
              </DisabledReason>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>What everyone else sees</CardTitle>
          <CardDescription>
            Shown on the maintenance page and above the sign-in screen. Visible without signing in, so
            say nothing here you would not publish.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="maintenance-message">Message</Label>
            <Input
              id="maintenance-message"
              value={message}
              maxLength={MESSAGE_MAX}
              placeholder="The platform is closed for scheduled maintenance."
              onChange={(event) => setMessage(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="maintenance-return">Expected back (optional, your local time)</Label>
            <Input
              id="maintenance-return"
              type="datetime-local"
              value={returnAt}
              onChange={(event) => setReturnAt(event.target.value)}
            />
          </div>
          {saveError ? (
            <p role="alert" className="text-sm text-destructive">
              {describeError(saveError)}
            </p>
          ) : null}
          {state.closed ? (
            <Button
              variant="outline"
              disabled={save.isPending}
              onClick={async () => {
                setSaveError(null);
                try {
                  await save.mutateAsync({ ...notice, expected_revision: state.revision });
                } catch (caught) {
                  setSaveError(caught);
                }
              }}
            >
              {save.isPending ? 'Saving…' : 'Save message'}
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">Used when you close the platform.</p>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmEnter}
        onOpenChange={setConfirmEnter}
        title="Close the platform for maintenance?"
        destructive
        confirmLabel="Close now"
        description="This happens immediately. Every account except platform administrators is signed out and cannot sign back in until you reopen, and must sign in again afterwards. Every API key, chat, the assistant, knowledge search and every model action are refused for everyone, administrators included. API keys are not revoked and work again after reopening."
        onConfirm={async () => {
          await enter.mutateAsync(notice);
        }}
      />
      <ConfirmDialog
        open={confirmReopen}
        onOpenChange={setConfirmReopen}
        title="Reopen the platform?"
        confirmLabel="Reopen"
        description="Every entrance starts serving again. Accounts that were signed out sign in again; API keys work unchanged."
        onConfirm={async () => {
          await reopen.mutateAsync();
        }}
      />
    </div>
  );
}
