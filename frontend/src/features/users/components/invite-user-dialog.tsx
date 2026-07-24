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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { OneTimeSecret } from '@/components/composed/one-time-secret';
import { describeError } from '@/components/composed/error-state';
import { useCreateUser } from '@/features/users/hooks/use-users';
import {
  createUserSchema,
  roleSchema,
  ROLE_LABELS,
  type CreateUserInput,
} from '@/features/users/schema';

export function InviteUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const create = useCreateUser();
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  const form = useForm<CreateUserInput>({
    resolver: zodResolver(createUserSchema),
    defaultValues: { login: '', display_name: '', role: 'user' },
  });

  async function onSubmit(values: CreateUserInput) {
    const result = await create.mutateAsync(values);
    // The URL exists in this response and nowhere else. Nothing is emailed.
    setInviteUrl(result.invitation.url ?? null);
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
      // The link is single-use and never shown again, so a stray Escape while
      // it is on screen loses it.
      locked={inviteUrl !== null && !acknowledged}
      onOpenChange={(next) => {
        if (!next) close();
        else onOpenChange(true);
      }}
      className="sm:max-w-lg"
    >
      <>
        <DialogHeader>
          <DialogTitle>Invite a user</DialogTitle>
          <DialogDescription>
            Accounts are invitation only. The recipient sets their own password
            and enrols TOTP; the platform never transmits a credential.
          </DialogDescription>
        </DialogHeader>

        {inviteUrl ? (
          <>
            <OneTimeSecret
              title="Single-use invitation link"
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
                id="invite-user-form"
                className="space-y-4"
                onSubmit={form.handleSubmit(onSubmit)}
              >
                <FormField
                  control={form.control}
                  name="login"
                  label="Login"
                  type="email"
                  placeholder="person@example.org"
                  autoComplete="off"
                />
                <FormField
                  control={form.control}
                  name="display_name"
                  label="Display name"
                  autoComplete="off"
                />
                <FormField
                  control={form.control}
                  name="role"
                  label="Role"
                  render={(field) => (
                    <Select
                      value={field.value as string}
                      onValueChange={(value) => field.onChange(value)}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {roleSchema.options.map((role) => (
                          <SelectItem key={role} value={role}>
                            {ROLE_LABELS[role]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
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
              <Button
                type="submit"
                form="invite-user-form"
                disabled={create.isPending}
              >
                {create.isPending ? 'Creating...' : 'Create and issue link'}
              </Button>
            </DialogFooter>
          </>
        )}
      </>
    </SecretDialog>
  );
}
