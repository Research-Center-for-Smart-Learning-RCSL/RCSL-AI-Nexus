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
  useRestoreAfterMaintenance,
  useRetryMaintenance,
  useSetMaintenanceMessage,
} from '../hooks/use-maintenance-admin';
import { formatExpectedReturn } from '../format';
import {
  canRetry,
  currentOperation,
  milestones,
  restoreBlocker,
  type Milestone,
} from '../progress';
import { MaintenanceProgress } from './maintenance-progress';

const MESSAGE_MAX = 500;

const MILESTONE: Record<Milestone, string> = {
  not_started: 'Not started',
  running: 'In progress',
  done: 'Done',
  failed: 'Stopped with an error',
};

/**
 * Close the platform, release and restore its runtimes, and reopen it (#61),
 * and edit what everyone else is shown.
 *
 * What closing does is stated in the confirmation rather than left to the
 * button's label, because it is immediate and reaches everybody: every account
 * but a platform administrator is signed out on the spot, and nobody,
 * administrators included, reaches a model until it reopens. Access closing,
 * the runtimes being released and the models coming back are shown apart:
 * the first is immediate, the other two take time and can fail.
 */
export function MaintenanceConsole() {
  const query = useMaintenanceAdmin();
  const enter = useEnterMaintenance();
  const reopen = useReopenAfterMaintenance();
  const restore = useRestoreAfterMaintenance();
  const retry = useRetryMaintenance();
  const save = useSetMaintenanceMessage();

  const [message, setMessage] = useState('');
  const [returnAt, setReturnAt] = useState('');
  const [confirmEnter, setConfirmEnter] = useState(false);
  const [confirmReopen, setConfirmReopen] = useState(false);
  const [confirmRestore, setConfirmRestore] = useState(false);
  const [retryError, setRetryError] = useState<unknown>(null);
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
  const operation = currentOperation(state);
  const progress = milestones(state);
  const restoreDisabled = restoreBlocker(state);

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
          {state.closed ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
              <dt className="text-muted-foreground">Access closed</dt>
              <dd>Done</dd>
              <dt className="text-muted-foreground">Runtimes released</dt>
              <dd>{MILESTONE[progress.released]}</dd>
              <dt className="text-muted-foreground">Models restored</dt>
              <dd>{MILESTONE[progress.restored]}</dd>
            </dl>
          ) : null}
          {retryError ? (
            <p role="alert" className="text-sm text-destructive">
              {describeError(retryError)}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2 pt-2">
            {state.closed ? (
              <>
                <DisabledReason reason={restoreDisabled}>
                  <Button
                    disabled={Boolean(restoreDisabled)}
                    onClick={() => setConfirmRestore(true)}
                  >
                    Restore and reopen
                  </Button>
                </DisabledReason>
                {canRetry(state) ? (
                  <Button
                    variant="outline"
                    disabled={retry.isPending}
                    onClick={async () => {
                      setRetryError(null);
                      try {
                        await retry.mutateAsync();
                      } catch (caught) {
                        setRetryError(caught);
                      }
                    }}
                  >
                    {retry.isPending ? 'Retrying…' : 'Retry'}
                  </Button>
                ) : null}
                <Button variant="outline" onClick={() => setConfirmReopen(true)}>
                  Reopen without restoring
                </Button>
              </>
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

      {operation ? <MaintenanceProgress operation={operation} /> : null}

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
        description="This happens immediately. Every account except platform administrators is signed out and cannot sign back in until you reopen, and must sign in again afterwards. Every API key, chat, the assistant, knowledge search and every model action are refused for everyone, administrators included. Generations already running are cut off, and every runtime is restarted with nothing loaded to release its memory; what each held is saved so it can be restored. API keys are not revoked and work again after reopening."
        onConfirm={async () => {
          await enter.mutateAsync(notice);
        }}
      />
      <ConfirmDialog
        open={confirmRestore}
        onOpenChange={setConfirmRestore}
        title="Restore the models and reopen?"
        confirmLabel="Restore"
        description="Every node loads back what it held before the entry, with the same weights and context, and each model is checked. The platform stays closed until every node verifies, then reopens on its own. If a step fails it stays closed and you can retry."
        onConfirm={async () => {
          await restore.mutateAsync();
        }}
      />
      <ConfirmDialog
        open={confirmReopen}
        onOpenChange={setConfirmReopen}
        title="Reopen without restoring?"
        destructive
        confirmLabel="Reopen"
        description="Every entrance starts serving again now, with whatever the runtimes hold, which after an entry is nothing: models load on first use or by hand. An entry or restore still in progress is stopped. Accounts that were signed out sign in again; API keys work unchanged."
        onConfirm={async () => {
          await reopen.mutateAsync();
        }}
      />
    </div>
  );
}
