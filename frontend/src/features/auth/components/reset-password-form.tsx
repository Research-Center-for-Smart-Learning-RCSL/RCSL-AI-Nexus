'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { FormField } from '@/components/composed/form-field';
import { ErrorState, describeError } from '@/components/composed/error-state';
import { resetPassword, verifyResetToken } from '@/features/auth/api';
import { PasswordStrengthMeter } from '@/features/auth/components/password-strength-meter';
import {
  resetPasswordSchema,
  type ResetPasswordInput,
} from '@/features/auth/password-schema';

/**
 * Consuming an administrator-issued reset link.
 *
 * No TOTP enrolment here, unlike invitation acceptance: the account already
 * has a second factor and the reset replaces only the password. The next sign
 * in still needs the authenticator, which is why the link alone is not enough
 * to reach the account (security.md section 5.4).
 */
export function ResetPasswordForm({ token }: { token: string }) {
  const router = useRouter();

  // Validated before the form renders, so a spent or expired link fails now
  // rather than after the user has chosen a password.
  const target = useQuery({
    queryKey: ['password-reset', token],
    queryFn: () => verifyResetToken(token),
    retry: false,
  });

  const form = useForm<ResetPasswordInput>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { password: '', password_confirmation: '' },
  });

  const password = form.watch('password');

  const submit = useMutation({
    mutationFn: (values: ResetPasswordInput) =>
      resetPassword({ token, password: values.password }),
    // Every session for that account is now gone, including any this browser
    // held, so there is nothing to return to except the sign-in screen.
    onSuccess: () => router.replace('/login'),
  });

  if (target.isPending) {
    return <p className="text-sm text-muted-foreground">Checking this link...</p>;
  }

  if (target.isError) {
    return (
      <ErrorState
        title="This link is no longer valid"
        error="Reset links expire and can only be used once. Ask an administrator for a new one."
      />
    );
  }

  return (
    <Form {...form}>
      <form
        className="space-y-6"
        onSubmit={form.handleSubmit((values) => submit.mutateAsync(values))}
      >
        <p className="text-sm text-muted-foreground">
          Resetting <span className="font-medium">{target.data.login}</span>
        </p>

        <FormField
          control={form.control}
          name="password"
          label="New password"
          type="password"
          autoComplete="new-password"
        />
        <PasswordStrengthMeter password={password} />

        <FormField
          control={form.control}
          name="password_confirmation"
          label="Confirm password"
          type="password"
          autoComplete="new-password"
        />

        {submit.isError && (
          <p className="text-sm text-destructive">{describeError(submit.error)}</p>
        )}

        <Button type="submit" className="w-full" disabled={submit.isPending}>
          {submit.isPending ? 'Saving...' : 'Set password'}
        </Button>
      </form>
    </Form>
  );
}
