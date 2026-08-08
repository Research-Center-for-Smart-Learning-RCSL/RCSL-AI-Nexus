'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { ErrorState } from '@/components/composed/error-state';
import { Spinner } from '@/components/composed/spinner';
import { ConfirmDialog } from '@/components/composed/confirm-dialog';
import {
  useRetentionPolicies,
  usePurgeDataset,
  usePurgePreview,
  useSetRetentionPolicy,
} from '@/features/retention/hooks/use-retention';
import {
  DATASET_DESCRIPTIONS,
  DATASET_LABELS,
  RETENTION_BOUNDS,
  type RetentionPolicy,
} from '@/features/retention/schema';

function formatWhen(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '';
}

/**
 * One dataset: its window, what changing it would remove, and a purge.
 *
 * The count is the point of the screen. "Keep 90 days" is an abstraction until
 * something says it deletes 4,000 audit entries, and the difference between
 * those two sentences is whether anybody thinks before saving. So the preview
 * runs against the number in the field rather than the number in the database,
 * and it runs before the save rather than reporting after it.
 */
function DatasetRow({ policy }: { policy: RetentionPolicy }) {
  const [days, setDays] = useState(String(policy.days));
  const [confirmingPurge, setConfirmingPurge] = useState(false);
  const save = useSetRetentionPolicy();
  const purge = usePurgeDataset();

  // Per dataset, because the two shapes are opposite: `audit_log` refuses a
  // window that is too short, `prompt_logs` one that is too long. A single
  // shared floor of 30 applied to a dataset whose ceiling is 30 would refuse
  // every value the server accepts, in the form, so nothing would ever reach
  // the error that explains which direction was wrong.
  const bounds = RETENTION_BOUNDS[policy.dataset];
  const parsed = Number(days);
  const valid =
    Number.isInteger(parsed) &&
    parsed >= bounds.min &&
    (bounds.max === null || parsed <= bounds.max);
  const changed = valid && parsed !== policy.days;

  // Asked for whatever is in the field once it is a usable number, including
  // when it equals the stored one — "what does the current policy delete right
  // now" is the question somebody opens this screen with.
  const preview = usePurgePreview(policy.dataset, valid ? parsed : undefined, valid);

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="font-heading text-sm font-semibold">
            {DATASET_LABELS[policy.dataset]}
          </h2>
          <p className="max-w-prose text-xs text-muted-foreground">
            {DATASET_DESCRIPTIONS[policy.dataset]}
          </p>
        </div>
        {policy.updated_by ? (
          <Badge variant="outline" className="shrink-0">
            set by {policy.updated_by} {formatWhen(policy.updated_at)}
          </Badge>
        ) : (
          // Never touched, which is not the same as "set to 360 by somebody".
          <Badge variant="outline" className="shrink-0">
            default
          </Badge>
        )}
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-muted-foreground">
          Keep for
          <Input
            type="number"
            min={bounds.min}
            {...(bounds.max === null ? {} : { max: bounds.max })}
            value={days}
            onChange={(event) => setDays(event.target.value)}
            aria-label={`Retention in days for ${DATASET_LABELS[policy.dataset]}`}
            className="mt-1 w-28"
          />
        </label>
        <span className="pb-2 text-sm text-muted-foreground">
          days{' '}
          <span className="text-xs">
            {bounds.max === null ? `(${bounds.min} or more)` : `(${bounds.min}–${bounds.max})`}
          </span>
        </span>

        <Button
          size="sm"
          disabled={!changed || save.isPending}
          onClick={() => save.mutate({ dataset: policy.dataset, days: parsed })}
        >
          {save.isPending ? 'Saving...' : 'Save'}
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="text-destructive"
          disabled={!valid || purge.isPending}
          onClick={() => setConfirmingPurge(true)}
        >
          Purge now
        </Button>
      </div>

      {!valid ? (
        // The message has to name the direction that is wrong, not just the
        // bound. "At least 30" on a dataset capped at 30 reads as a typo in the
        // product rather than as a rule, and the two rules exist for opposite
        // reasons: forgetting too soon, and keeping prompt text too long.
        <p className="text-xs text-destructive">
          {bounds.max === null
            ? `Enter a whole number of days, at least ${bounds.min}.`
            : `Enter a whole number of days between ${bounds.min} and ${bounds.max}. This record type may not be kept longer than that.`}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          {preview.isLoading ? (
            <Spinner label="Counting" />
          ) : preview.data ? (
            preview.data.affected === 0 ? (
              `Nothing is older than ${parsed} days, so this would remove nothing today.`
            ) : (
              <>
                <strong>
                  {preview.data.affected.toLocaleString()} record
                  {preview.data.affected === 1 ? '' : 's'}
                </strong>{' '}
                {changed ? 'would be removed by this window' : 'are past this window'}, the
                oldest first. This is a permanent deletion.
              </>
            )
          ) : null}
        </p>
      )}

      {save.error ? <ErrorState error={save.error} /> : null}
      {purge.error ? <ErrorState error={purge.error} /> : null}
      {purge.data ? (
        <p className="text-xs text-muted-foreground">
          Removed {purge.data.deleted.toLocaleString()} record
          {purge.data.deleted === 1 ? '' : 's'} older than{' '}
          {new Date(purge.data.cutoff).toLocaleString()}.
        </p>
      ) : null}

      <ConfirmDialog
        open={confirmingPurge}
        onOpenChange={setConfirmingPurge}
        title={`Purge ${DATASET_LABELS[policy.dataset]}?`}
        description={
          // The count again, because the confirm dialog is the last place it
          // can change somebody's mind, and it is the number they are agreeing
          // to rather than the window.
          preview.data && preview.data.affected > 0
            ? `This permanently deletes ${preview.data.affected.toLocaleString()} record(s) older than ${parsed} days. It cannot be undone.`
            : `Nothing is older than ${parsed} days right now, so this will delete nothing.`
        }
        confirmLabel="Purge"
        destructive
        onConfirm={async () => {
          await purge.mutateAsync({ dataset: policy.dataset, days: parsed });
        }}
      />
    </div>
  );
}

export function RetentionPanel() {
  // No assistant surface registered. The surface union is closed and shared
  // with the backend's guidance map, so adding one is a change in three files
  // and a decision about what the assistant should say about deleting records
  // — worth doing deliberately rather than as a side effect of this screen.
  const { data, isLoading, error, refetch } = useRetentionPolicies();

  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (isLoading || !data) return <Spinner label="Loading retention settings" />;

  return (
    <div className="space-y-3">
      {data.map((policy) => (
        // Keyed by the stored window as well as the dataset, so a saved change
        // remounts the row and the field starts from what is now stored rather
        // than holding the value the user typed into a form that has moved on.
        <DatasetRow key={`${policy.dataset}:${policy.days}`} policy={policy} />
      ))}
    </div>
  );
}
