'use client';

import { useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Form } from '@/components/ui/form';
import { FormField } from '@/components/composed/form-field';
import { describeError } from '@/components/composed/error-state';
import { changePassword } from '@/features/auth/api';
import { PasswordStrengthMeter } from '@/features/auth/components/password-strength-meter';
import {
  makeChangePasswordSchema,
  type ChangePasswordInput,
} from '@/features/auth/password-schema';
import { useMe } from '@/lib/session';

/**
 * Changing your own password.
 *
 * The consequence stated in the description is the one people are surprised by:
 * the use case invalidates every *other* session and keeps this one, because
 * the usual reason to change a password is that the old one may be in someone
 * else's hands and leaving their session alive would make the change cosmetic.
 */
export function ChangePasswordForm() {
  // The account's own login and name, so a password built out of either is
  // refused here rather than by the API, which scores against both.
  const me = useMe();
  const userInputs = useMemo(() => [me.login, me.display_name], [me.login, me.display_name]);

  const form = useForm<ChangePasswordInput>({
    resolver: zodResolver(makeChangePasswordSchema(userInputs)),
    defaultValues: {
      current_password: '',
      password: '',
      password_confirmation: '',
    },
  });

  const password = form.watch('password');

  const change = useMutation({
    mutationFn: (values: ChangePasswordInput) => changePassword(values),
    onSuccess: () => {
      toast.success('Password changed. Every other session has been signed out.');
      form.reset();
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Password</CardTitle>
        <CardDescription>
          Changing it signs out every other session and keeps this one. Your
          authenticator is unaffected.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form
            className="space-y-4"
            onSubmit={form.handleSubmit((values) => change.mutateAsync(values))}
          >
            <FormField
              control={form.control}
              name="current_password"
              label="Current password"
              type="password"
              autoComplete="current-password"
            />

            <FormField
              control={form.control}
              name="password"
              label="New password"
              type="password"
              autoComplete="new-password"
            />
            <PasswordStrengthMeter password={password} userInputs={userInputs} />

            <FormField
              control={form.control}
              name="password_confirmation"
              label="Confirm new password"
              type="password"
              autoComplete="new-password"
            />

            {change.isError ? (
              // Shown inline rather than only as a toast: a wrong current
              // password, and a new one the server judges too weak or identical
              // to the old, all land here and each needs the field edited.
              <p role="alert" className="text-sm text-destructive">
                {describeError(change.error)}
              </p>
            ) : null}

            <Button type="submit" disabled={change.isPending}>
              {change.isPending ? 'Changing...' : 'Change password'}
            </Button>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}
