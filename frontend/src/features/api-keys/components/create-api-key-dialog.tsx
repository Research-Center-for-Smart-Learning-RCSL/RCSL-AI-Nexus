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
import {
  createApiKeySchema,
  defaultExpiry,
  DEFAULT_EXPIRY_DAYS,
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
  const { isAdmin } = useSession();
  const issue = useIssueApiKey();
  // `api_key:write_any` is what lets an administrator issue on someone's
  // behalf, and the endpoint has taken `owner_id` all along. Fetched only for
  // them, because listing users needs a scope a member does not hold.
  const owners = useUsers({ enabled: isAdmin && open });
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
    },
  });

  const scopes = form.watch('scopes');

  async function onSubmit(values: CreateApiKeyValues) {
    const result = await issue.mutateAsync({
      name: values.name,
      owner_id: values.owner_id,
      scopes: values.scopes,
      rate_limit_rpm: values.rate_limit_rpm,
      quota_tokens_per_day: values.quota_tokens_per_day,
      allowed_cidrs: parseCidrText(values.allowed_cidrs_text),
      expires_at: values.expires_at,
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
            <div className="max-h-[60vh] space-y-5 overflow-y-auto">
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

                {isAdmin ? (
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
