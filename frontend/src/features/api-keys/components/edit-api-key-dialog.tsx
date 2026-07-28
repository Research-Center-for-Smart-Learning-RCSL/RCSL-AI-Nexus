'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Form } from '@/components/ui/form';
import { FormField } from '@/components/composed/form-field';
import { describeError } from '@/components/composed/error-state';
import { CapabilityPicker } from '@/features/api-keys/components/capability-picker';
import { useUpdateApiKey } from '@/features/api-keys/hooks/use-api-keys';
import {
  defaultExpiry,
  keyStatus,
  parseCidrText,
  toDateInput,
  updateApiKeySchema,
  type ApiKey,
  type UpdateApiKeyInput,
  type UpdateApiKeyValues,
} from '@/features/api-keys/schema';

/**
 * Editing what a key is allowed to do, without reissuing it.
 *
 * The secret is untouched by every field here, which is what makes this
 * different from issuing: nothing unrecoverable is on screen, so this is an
 * ordinary dialog rather than a `SecretDialog`.
 *
 * Two fields are deliberately absent. `owner_id`, because permission is
 * checked against the key's current owner and an edit cannot move it. And the
 * key itself, because it is not stored — a compromised key is revoked and
 * replaced, not edited.
 *
 * Mount this only while a key is selected, and key it by `key_id`: the form's
 * defaults are read once, so a mounted instance handed a different key would
 * go on showing the first one's values.
 */
export function EditApiKeyDialog({
  apiKey,
  onOpenChange,
}: {
  apiKey: ApiKey;
  onOpenChange: (open: boolean) => void;
}) {
  const update = useUpdateApiKey(apiKey.key_id);

  const form = useForm<UpdateApiKeyInput, unknown, UpdateApiKeyValues>({
    resolver: zodResolver(updateApiKeySchema),
    defaultValues: {
      name: apiKey.name,
      scopes: apiKey.scopes,
      rate_limit_rpm: apiKey.rate_limit_rpm,
      quota_tokens_per_day: apiKey.quota_tokens_per_day,
      allowed_cidrs_text: apiKey.allowed_cidrs.join('\n'),
      // Extending an expired key is the main reason to open this dialog, and
      // resubmitting the date it already carries can only be refused for not
      // being in the future. So an expired key opens on a date that works.
      expires_at:
        keyStatus(apiKey) === 'expired'
          ? defaultExpiry()
          : toDateInput(apiKey.expires_at),
    },
  });

  const scopes = form.watch('scopes');

  function onSubmit(values: UpdateApiKeyValues) {
    update.mutate(
      {
        name: values.name,
        scopes: values.scopes,
        rate_limit_rpm: values.rate_limit_rpm,
        quota_tokens_per_day: values.quota_tokens_per_day,
        allowed_cidrs: parseCidrText(values.allowed_cidrs_text),
        expires_at: values.expires_at,
      },
      // Closed only once the server has accepted it. A dialog that closes on a
      // rejected edit leaves the operator believing a limit was tightened.
      { onSuccess: () => onOpenChange(false) },
    );
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit {apiKey.name}</DialogTitle>
          <DialogDescription>
            Changes apply to the next request; the gateway re-reads the key
            every time. The secret does not change, so nothing has to be
            redeployed.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            id="edit-api-key-form"
            className="space-y-4"
            onSubmit={form.handleSubmit(onSubmit)}
          >
            <FormField
              control={form.control}
              name="name"
              label="Name"
              description={
                <>
                  Shown alongside{' '}
                  <span className="font-mono">{apiKey.key_id}</span>.
                </>
              }
            />

            <CapabilityPicker
              value={scopes}
              onChange={(next) =>
                form.setValue('scopes', next, { shouldValidate: true })
              }
              error={form.formState.errors.scopes?.message}
            />
            <p className="-mt-2 text-sm text-muted-foreground">
              Narrowing these is what limits a key that has leaked; the change
              is recorded in the audit log by name.
            </p>

            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="rate_limit_rpm"
                label="Rate limit (rpm)"
                type="number"
              />
              <FormField
                control={form.control}
                name="quota_tokens_per_day"
                label="Daily token quota"
                type="number"
              />
            </div>

            <FormField
              control={form.control}
              name="expires_at"
              label="Expires"
              type="date"
              description="Must be in the future, and within a year. Extending is how a key is kept alive without reissuing it."
            />

            <FormField
              control={form.control}
              name="allowed_cidrs_text"
              label="Allowed source CIDRs"
              description="One per line or comma separated. Empty means no source restriction."
              render={(field) => (
                <textarea
                  id="edit-allowed-cidrs"
                  value={(field.value as string) ?? ''}
                  onChange={(event) => field.onChange(event.target.value)}
                  onBlur={field.onBlur}
                  rows={2}
                  placeholder="203.0.113.0/24"
                  className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              )}
            />

            {update.error ? (
              <p role="alert" className="text-sm text-destructive">
                {describeError(update.error)}
              </p>
            ) : null}
          </form>
        </Form>

        <DialogFooter>
          <DialogClose
            render={<Button variant="outline" disabled={update.isPending} />}
          >
            Cancel
          </DialogClose>
          <Button
            type="submit"
            form="edit-api-key-form"
            disabled={update.isPending}
          >
            {update.isPending ? 'Saving...' : 'Save changes'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
