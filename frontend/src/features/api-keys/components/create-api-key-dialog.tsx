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
import { Label } from '@/components/ui/label';
import { FormField } from '@/components/composed/form-field';
import { SecretDialog } from '@/components/composed/secret-dialog';
import { OneTimeSecret } from '@/components/composed/one-time-secret';
import { describeError } from '@/components/composed/error-state';
import { capabilitySchema, type Capability } from '@/features/models/schema';
import { useIssueApiKey } from '@/features/api-keys/hooks/use-api-keys';
import {
  createApiKeySchema,
  defaultExpiry,
  DEFAULT_EXPIRY_DAYS,
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
  ownerId: string;
}) {
  const issue = useIssueApiKey();
  const [plaintext, setPlaintext] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [cidrText, setCidrText] = useState('');

  const form = useForm<CreateApiKeyInput, unknown, CreateApiKeyValues>({
    resolver: zodResolver(createApiKeySchema),
    defaultValues: {
      name: '',
      scopes: ['chat'],
      rate_limit_rpm: 60,
      quota_tokens_per_day: 1_000_000,
      allowed_cidrs: [],
      expires_at: defaultExpiry(),
      owner_id: ownerId,
    },
  });

  const scopes = form.watch('scopes');

  async function onSubmit(values: CreateApiKeyValues) {
    const cidrs = cidrText
      .split(/[\s,]+/)
      .map((entry) => entry.trim())
      .filter(Boolean);
    const result = await issue.mutateAsync({ ...values, allowed_cidrs: cidrs });
    setPlaintext(result.plaintext);
  }

  function close() {
    onOpenChange(false);
    setPlaintext(null);
    setAcknowledged(false);
    setCidrText('');
    form.reset();
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
            Scopes are minimal by default. Expiry is required, which is what
            forces rotation.
          </DialogDescription>
        </DialogHeader>

        {plaintext ? (
          <>
            <OneTimeSecret
              title="The key, shown once"
              description="Only a peppered hash is stored, so this cannot be retrieved later. If it is lost, revoke and issue a new one."
              values={[plaintext]}
              acknowledgement="I have saved this key"
              onAcknowledgedChange={setAcknowledged}
            />
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

                <div className="space-y-2">
                  <Label>Scopes</Label>
                  <div className="flex flex-wrap gap-3">
                    {capabilitySchema.options.map((option) => (
                      <label
                        key={option}
                        className="flex items-center gap-1.5 text-sm"
                      >
                        <input
                          type="checkbox"
                          checked={scopes.includes(option)}
                          onChange={(event) => {
                            const next = event.target.checked
                              ? [...scopes, option as Capability]
                              : scopes.filter((scope) => scope !== option);
                            form.setValue('scopes', next, {
                              shouldValidate: true,
                            });
                          }}
                        />
                        {option}
                      </label>
                    ))}
                  </div>
                  {form.formState.errors.scopes ? (
                    <p className="text-sm text-destructive">
                      {form.formState.errors.scopes.message}
                    </p>
                  ) : null}
                </div>

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

                <div className="space-y-2">
                  <Label htmlFor="allowed-cidrs">Allowed source CIDRs</Label>
                  <textarea
                    id="allowed-cidrs"
                    value={cidrText}
                    onChange={(event) => setCidrText(event.target.value)}
                    rows={2}
                    placeholder="203.0.113.0/24"
                    className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  />
                  <p className="text-sm text-muted-foreground">
                    One per line or comma separated. Leave empty for no source
                    restriction.
                  </p>
                </div>

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
