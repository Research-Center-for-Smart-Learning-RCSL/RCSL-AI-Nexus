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
import { DisabledReason } from '@/components/composed/disabled-reason';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { describeError } from '@/components/composed/error-state';
import { useUpdateUser } from '@/features/users/hooks/use-users';
import {
  roleSchema,
  ROLE_LABELS,
  updateUserSchema,
  type UpdateUserInput,
  type User,
} from '@/features/users/schema';

/**
 * Editing a user's display name and role.
 *
 * `PATCH /admin/users/{id}`, `updateUser`, `updateUserSchema` and
 * `useUpdateUser` all existed and were reachable from nothing: the hook had no
 * caller anywhere in the application. So a display name was whatever it was
 * given at invitation and could never be corrected, and an administrator could
 * not promote anybody — the one operation that lets a second administrator
 * exist. Both reports arrived the same day and are the same missing screen.
 *
 * Mounted only while a row is selected, so `useUpdateUser(user.id)` is fixed
 * for the life of the component and the form's `defaultValues` are the right
 * user's. Keeping it mounted and swapping the prop would leave both stale —
 * the same reconciliation trap that ate every keystroke in the login form on
 * 2026-08-04.
 */
export function EditUserDialog({
  user,
  onClose,
  isSelf,
}: {
  user: User;
  onClose: () => void;
  isSelf: boolean;
}) {
  const update = useUpdateUser(user.id);

  const form = useForm<UpdateUserInput>({
    resolver: zodResolver(updateUserSchema),
    defaultValues: { display_name: user.display_name, role: user.role },
  });

  async function onSubmit(values: UpdateUserInput) {
    await update.mutateAsync(values);
    onClose();
  }

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent>
      <DialogHeader>
        <DialogTitle>Edit {user.display_name}</DialogTitle>
        <DialogDescription>
          {user.login}. Changing a role ends that user&apos;s sessions, because
          scopes are derived from the role when a request arrives rather than at
          sign-in.
        </DialogDescription>
      </DialogHeader>

      <Form {...form}>
        <form
          id="edit-user-form"
          className="space-y-4"
          onSubmit={form.handleSubmit(onSubmit)}
        >
          <FormField
            control={form.control}
            name="display_name"
            label="Display name"
            autoComplete="off"
          />
          {/* Off for a reason specific to the row, so the reason travels with
              it: the backend refuses this outright, and on a
              single-administrator instance it would be unrecoverable. */}
          <DisabledReason
            reason={
              isSelf
                ? 'You cannot change your own role. Another administrator has to do it, which is what stops the last administrator demoting themselves.'
                : undefined
            }
          >
            <FormField
              control={form.control}
              name="role"
              label="Role"
              disabled={isSelf}
              render={(field) => (
                <Select
                  value={field.value as string}
                  onValueChange={(value) => field.onChange(value)}
                  disabled={isSelf}
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
          </DisabledReason>
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
        <Button type="submit" form="edit-user-form" disabled={update.isPending}>
          {update.isPending ? 'Saving...' : 'Save'}
        </Button>
      </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
