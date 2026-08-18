'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

import { Button } from '@/components/ui/button';
import { SecretDialog } from '@/components/composed/secret-dialog';
import {
  DialogClose,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Form } from '@/components/ui/form';
import { FormField } from '@/components/composed/form-field';
import { OneTimeSecret } from '@/components/composed/one-time-secret';
import { describeError } from '@/components/composed/error-state';
import { useCreateTenant } from '@/features/tenants/hooks/use-tenants';
import { createTenantSchema, type CreateTenantInput } from '@/features/tenants/schema';

export function CreateTenantDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const create = useCreateTenant();
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  const form = useForm<CreateTenantInput>({
    resolver: zodResolver(createTenantSchema),
    defaultValues: { name: '', first_admin_login: '', first_admin_display_name: '' },
  });

  async function onSubmit(values: CreateTenantInput) {
    try {
      const result = await create.mutateAsync(values);
      // The first admin's link exists in this response and nowhere else.
      setInviteUrl(result.invitation.url ?? null);
    } catch {
      // A failure (e.g. a duplicate name 409) is surfaced through create.error
      // below; swallow the rejection so it does not escape the submit handler.
    }
  }

  function close() {
    onOpenChange(false);
    setInviteUrl(null);
    setAcknowledged(false);
    form.reset();
  }

  return (
    <SecretDialog
      open={open}
      locked={inviteUrl !== null && !acknowledged}
      onOpenChange={(next) => {
        if (!next) close();
        else onOpenChange(true);
      }}
      className="sm:max-w-lg"
    >
      <>
        <DialogHeader>
          <DialogTitle>Create a tenant</DialogTitle>
          <DialogDescription>
            A tenant isolates its users, keys and usage from every other
            tenant. Creating one issues a single-use link for its first
            account — which is a platform administrator, so the boundary drawn
            here does not confine the person handed it.
          </DialogDescription>
        </DialogHeader>

        {inviteUrl ? (
          <>
            <OneTimeSecret
              title="First administrator's invitation link"
              description="Deliver this out of band. It expires in 72 hours, works once, and is not shown again."
              values={[inviteUrl]}
              acknowledgement="I have copied this link"
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
                id="create-tenant-form"
                className="space-y-4"
                onSubmit={form.handleSubmit(onSubmit)}
              >
                <FormField
                  control={form.control}
                  name="name"
                  label="Tenant name"
                  placeholder="Vision Lab"
                  autoComplete="off"
                />
                <FormField
                  control={form.control}
                  name="first_admin_login"
                  label="First administrator login"
                  type="email"
                  placeholder="lead@example.org"
                  autoComplete="off"
                  description="Globally unique. This account is created with the platform admin role: every scope, in every tenant, not only this one. Issue it to somebody who is already trusted with the whole installation, or invite a tenant_admin from inside the new tenant afterwards."
                />
                <FormField
                  control={form.control}
                  name="first_admin_display_name"
                  label="First administrator name"
                  autoComplete="off"
                />
                {create.error ? (
                  <p role="alert" className="text-sm text-destructive">
                    {describeError(create.error)}
                  </p>
                ) : null}
              </form>
            </Form>
            <DialogFooter>
              <DialogClose
                render={<Button variant="outline" disabled={create.isPending} />}
              >
                Cancel
              </DialogClose>
              <Button type="submit" form="create-tenant-form" disabled={create.isPending}>
                {create.isPending ? 'Creating...' : 'Create and issue link'}
              </Button>
            </DialogFooter>
          </>
        )}
      </>
    </SecretDialog>
  );
}
