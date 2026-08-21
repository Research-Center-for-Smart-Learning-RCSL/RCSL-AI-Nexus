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
import {
  ApiKeyCapabilities,
  CidrTextarea,
  DefaultCapabilitySelect,
} from '@/features/api-keys/components/api-key-policy-controls';
import { useUpdateApiKey } from '@/features/api-keys/hooks/use-api-keys';
import { useAssistantSurface } from '@/features/assistant/context';
import {
  applyProposalPatch,
  draftFor,
} from '@/features/api-keys/assistant-bridge';
import {
  defaultCapabilityField,
  defaultCapabilityOptions,
  defaultCapabilityPayload,
  defaultExpiry,
  keyStatus,
  NO_DEFAULT,
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

  // Extending an expired key is the main reason to open this dialog, and
  // resubmitting the date it already carries can only be refused for not being
  // in the future. So an expired key opens on a date that works — which also
  // means its prefilled value is deliberately not what is stored, and has to
  // be sent even if the operator never touches the field.
  const expired = keyStatus(apiKey) === 'expired';

  const form = useForm<UpdateApiKeyInput, unknown, UpdateApiKeyValues>({
    resolver: zodResolver(updateApiKeySchema),
    defaultValues: {
      name: apiKey.name,
      scopes: apiKey.scopes,
      rate_limit_rpm: apiKey.rate_limit_rpm,
      quota_tokens_per_day: apiKey.quota_tokens_per_day,
      allowed_cidrs_text: apiKey.allowed_cidrs.join('\n'),
      expires_at: expired ? defaultExpiry() : toDateInput(apiKey.expires_at),
      default_capability: defaultCapabilityField(apiKey.default_capability),
    },
  });

  // This dialog is mounted only while a key is selected, so its presence is
  // the whole condition — unlike the create dialog, nothing here ever replaces
  // the form with a secret. `key_id` travels too, so a proposal can name the
  // key it is about; it is the public lookup handle and reveals nothing.
  useAssistantSurface({
    surface: 'api_keys.edit',
    keyId: apiKey.key_id,
    readDraft: () => draftFor(form.getValues()),
    applyPatch: (patch) =>
      applyProposalPatch(patch, (field, value) =>
        form.setValue(field, value as never, {
          shouldValidate: true,
          shouldDirty: true,
        }),
      ),
  });

  const scopes = form.watch('scopes');

  const defaultOptions = defaultCapabilityOptions(
    scopes,
    form.watch('default_capability') ?? NO_DEFAULT,
  );

  function onSubmit(values: UpdateApiKeyValues) {
    update.mutate(
      {
        name: values.name,
        scopes: values.scopes,
        rate_limit_rpm: values.rate_limit_rpm,
        quota_tokens_per_day: values.quota_tokens_per_day,
        allowed_cidrs: parseCidrText(values.allowed_cidrs_text),
        // Always sent, unlike the expiry below, and that is the point of the
        // field being handled specially on the server: `null` here clears a
        // default rather than meaning "leave it alone". Omitting it when
        // unchanged would work, and would also make "refuse again" the one
        // edit this dialog could not express.
        default_capability: defaultCapabilityPayload(values.default_capability),
        // Sent only when it is actually meant to change, which is what the
        // endpoint being a PATCH is for. A date input holds a calendar day, so
        // resubmitting an untouched value rewrites an `18:00Z` expiry to
        // midnight — every edit quietly shortening the key by up to a day, and
        // a key expiring later today refusing every edit with "expiry is not
        // in the future". Renaming a key must not depend on the clock.
        ...(form.formState.dirtyFields.expires_at || expired
          ? { expires_at: values.expires_at }
          : {}),
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

            <ApiKeyCapabilities
              scopes={scopes}
              onChange={(next) =>
                form.setValue('scopes', next, { shouldValidate: true })
              }
              error={form.formState.errors.scopes?.message}
            />
            <p className="-mt-2 text-sm text-muted-foreground">
              Narrowing these is what limits a key that has leaked; the change
              is recorded in the audit log by name.
            </p>

            {/* Directly under the capabilities, because it can only ever name
                one of them — and narrowing them out from under it is refused
                rather than silently clearing it, so the two belong together. */}
            <FormField
              control={form.control}
              name="default_capability"
              label="When a request names something else"
              description="A request names a capability in its model field. Most clients send a model name instead, and Codex's own picker overrides a configured model line; the refusal is what informs the holder of this. Set a capability only where convenience outweighs that signal. Substituted requests are recorded in either case."
              render={(field) => (
                <DefaultCapabilitySelect
                      value={field.value as string}
                      onChange={(value) => field.onChange(value)}
                      scopes={scopes}
                      options={defaultOptions}
                    />
              )}
            />

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
                description="Rolling 24 hours, prompt included. Raising it takes effect on the next request; it does not clear spend already in the window."
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
                <CidrTextarea
                      id="edit-allowed-cidrs"
                      value={(field.value as string) ?? ''}
                      onChange={(value) => field.onChange(value)}
                      onBlur={field.onBlur}
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
