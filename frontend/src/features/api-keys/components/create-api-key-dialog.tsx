'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

import { Button } from '@/components/ui/button';
import {
  DialogClose,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Form } from '@/components/ui/form';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { FormField } from '@/components/composed/form-field';
import { SecretDialog } from '@/components/composed/secret-dialog';
import { OneTimeSecret } from '@/components/composed/one-time-secret';
import { describeError } from '@/components/composed/error-state';
import { CapabilityPicker } from '@/features/api-keys/components/capability-picker';
import { useSession } from '@/lib/session';
import { useUsers } from '@/features/users/hooks/use-users';
import { IntegrationSnippet } from '@/features/gateway/components/integration-snippet';
import { useIssueApiKey } from '@/features/api-keys/hooks/use-api-keys';
import { useAssistantSurface } from '@/features/assistant/context';
import { applyProposalPatch, draftFor } from '@/features/api-keys/assistant-bridge';
import {
  createApiKeySchema,
  defaultCapabilityOptions,
  defaultCapabilityPayload,
  defaultExpiry,
  DEFAULT_EXPIRY_DAYS,
  NO_DEFAULT,
  parseCidrText,
  type CreateApiKeyInput,
  type CreateApiKeyValues,
} from '@/features/api-keys/schema';

export function CreateApiKeyDialog({
  open,
  onOpenChange,
  ownerId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whose key this is by default: the caller's own. */
  ownerId: string;
}) {
  const { can } = useSession();
  // The two scopes are asked for separately because they are held separately:
  // `api_key:write_any` is what lets a caller issue on someone else's behalf,
  // and `user:read` is what lets the picker be populated at all. An `operator`
  // holds the second and not the first — it may look users up but may not
  // issue for them — so asking one question would have offered a picker whose
  // submission the server refuses.
  const mayWriteAny = can('api_key:write_any');
  const issue = useIssueApiKey();
  const owners = useUsers({ enabled: mayWriteAny && can('user:read') && open });
  const [plaintext, setPlaintext] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  // Captured at issue rather than read back off the form, which is reset when
  // the dialog closes and would leave the sample naming the wrong capability.
  const [issuedCapability, setIssuedCapability] = useState('chat');

  const form = useForm<CreateApiKeyInput, unknown, CreateApiKeyValues>({
    resolver: zodResolver(createApiKeySchema),
    defaultValues: {
      name: '',
      scopes: ['chat'],
      rate_limit_rpm: 60,
      quota_tokens_per_day: 1_000_000,
      allowed_cidrs_text: '',
      expires_at: defaultExpiry(),
      owner_id: ownerId,
      default_capability: NO_DEFAULT,
    },
  });

  const scopes = form.watch('scopes');

  const defaultOptions = defaultCapabilityOptions(
    scopes,
    form.watch('default_capability') ?? NO_DEFAULT,
  );

  // Published only while the form is on screen. Once `plaintext` is set the
  // dialog is showing a secret rather than a form, and there is nothing left to
  // advise on — `null` rather than another surface, so dismissing this dialog
  // hands the assistant back to the key list rather than blanking it.
  //
  // What travels is `draftFor(form.getValues())` and nothing else. The
  // plaintext is in scope on the very next line and has no field to arrive in.
  useAssistantSurface(
    open && plaintext === null
      ? {
          surface: 'api_keys.create',
          readDraft: () => draftFor(form.getValues()),
          applyPatch: (patch) =>
            applyProposalPatch(patch, (field, value) =>
              form.setValue(field, value as never, {
                shouldValidate: true,
                shouldDirty: true,
              }),
            ),
        }
      : null,
  );

  async function onSubmit(values: CreateApiKeyValues) {
    const result = await issue.mutateAsync({
      name: values.name,
      owner_id: values.owner_id,
      scopes: values.scopes,
      rate_limit_rpm: values.rate_limit_rpm,
      quota_tokens_per_day: values.quota_tokens_per_day,
      allowed_cidrs: parseCidrText(values.allowed_cidrs_text),
      expires_at: values.expires_at,
      default_capability: defaultCapabilityPayload(values.default_capability),
    });
    // The first capability, which is what a one-capability key makes obvious
    // and what a multi-capability key can reasonably start from.
    setIssuedCapability(values.scopes[0] ?? 'chat');
    setPlaintext(result.plaintext);
  }

  function close() {
    onOpenChange(false);
    setPlaintext(null);
    setAcknowledged(false);
    form.reset();
    // The mutation outlives the dialog's own state. Without this a rejected
    // issue leaves its error banner above a pristine form the next time the
    // dialog opens, reporting a refusal of something that was never submitted.
    issue.reset();
  }

  return (
    <SecretDialog
      open={open}
      // While the plaintext is on screen and unacknowledged, Escape, an
      // outside click, and the corner X are all disabled: each of them would
      // destroy the only copy that will ever exist.
      locked={plaintext !== null && !acknowledged}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      className="sm:max-w-lg"
    >
      <>
        <DialogHeader>
          <DialogTitle>Issue an API key</DialogTitle>
          <DialogDescription>
            Capabilities are minimal by default. Expiry is required, which is
            what forces rotation.
          </DialogDescription>
        </DialogHeader>

        {plaintext ? (
          <>
            <div className="max-h-[60vh] space-y-5 overflow-y-auto overscroll-contain">
              <OneTimeSecret
                title="The key, shown once"
                description="Only a peppered hash is stored, so this cannot be retrieved later. If it is lost, revoke and issue a new one."
                values={[plaintext]}
                acknowledgement="I have saved this key"
                onAcknowledgedChange={setAcknowledged}
              />
              {/* Shown here rather than left to documentation, because this is
                  the only moment the plaintext exists: a snippet the holder
                  has to come back and fill in is one they fill in wrongly. */}
              <IntegrationSnippet
                plaintext={plaintext}
                capability={issuedCapability}
              />
            </div>
            <DialogFooter>
              <Button disabled={!acknowledged} onClick={close}>
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <Form {...form}>
              <form
                id="api-key-form"
                className="space-y-4"
                onSubmit={form.handleSubmit(onSubmit)}
              >
                <FormField
                  control={form.control}
                  name="name"
                  label="Name"
                  placeholder="ci-pipeline"
                  description="Shown alongside the key id for identification."
                />

                {mayWriteAny ? (
                  <FormField
                    control={form.control}
                    name="owner_id"
                    label="Owner"
                    description="Who holds this key. Revoke it when they leave; deleting the account takes its keys with it."
                    render={(field) => (
                      <Select
                        value={field.value as string}
                        onValueChange={(value) => field.onChange(value)}
                        disabled={owners.isLoading}
                      >
                        <SelectTrigger className="w-full">
                          <SelectValue
                            placeholder={
                              owners.isLoading ? 'Loading...' : 'Choose an owner'
                            }
                          />
                        </SelectTrigger>
                        <SelectContent>
                          {(owners.data ?? []).map((user) => (
                            <SelectItem key={user.id} value={user.id}>
                              {user.display_name} ({user.login})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  />
                ) : null}

                <CapabilityPicker
                  value={scopes}
                  onChange={(next) =>
                    form.setValue('scopes', next, { shouldValidate: true })
                  }
                  error={form.formState.errors.scopes?.message}
                />

                {/* Under the capability picker, because it can only ever name
                    one of the boxes above it and the order says so. */}
                <FormField
                  control={form.control}
                  name="default_capability"
                  label="When a request names something else"
                  description="A request names a capability in its model field. Most clients send a model name instead — Codex's own picker overrides a configured model line — and refusing is what tells the integrator that. Choose a capability here only when you would rather this key just worked."
                  render={(field) => (
                    <Select
                      value={field.value as string}
                      onValueChange={(value) => field.onChange(value)}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NO_DEFAULT}>
                          Refuse, and say what this key may call
                        </SelectItem>
                        {defaultOptions.map((capability) => (
                          <SelectItem key={capability} value={capability}>
                            Serve {capability}
                            {(scopes as string[]).includes(capability)
                              ? ''
                              : ' (not among this key\u2019s capabilities)'}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
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
                    description="Rolling 24 hours, prompt included. An agent resends its whole conversation each turn, so a coding session costs far more than its replies suggest."
                  />
                </div>

                <FormField
                  control={form.control}
                  name="expires_at"
                  label="Expires"
                  type="date"
                  description={`Required. Defaults to ${DEFAULT_EXPIRY_DAYS} days.`}
                />

                {/* A form field rather than local state. Held separately, the
                    text was assembled after validation had already run against
                    an array the form never contained, so the CIDR rule beside
                    it could not fire and a typo surfaced as a server error. */}
                <FormField
                  control={form.control}
                  name="allowed_cidrs_text"
                  label="Allowed source CIDRs"
                  description="One per line or comma separated. Leave empty for no source restriction."
                  render={(field) => (
                    <textarea
                      id="allowed-cidrs"
                      value={(field.value as string) ?? ''}
                      onChange={(event) => field.onChange(event.target.value)}
                      onBlur={field.onBlur}
                      rows={2}
                      placeholder="203.0.113.0/24"
                      className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                    />
                  )}
                />

                {issue.error ? (
                  <p role="alert" className="text-sm text-destructive">
                    {describeError(issue.error)}
                  </p>
                ) : null}
              </form>
            </Form>
            <DialogFooter>
              <DialogClose
                render={<Button variant="outline" disabled={issue.isPending} />}
              >
                Cancel
              </DialogClose>
              <Button
                type="submit"
                form="api-key-form"
                disabled={issue.isPending}
              >
                {issue.isPending ? 'Issuing...' : 'Issue key'}
              </Button>
            </DialogFooter>
          </>
        )}
      </>
    </SecretDialog>
  );
}
