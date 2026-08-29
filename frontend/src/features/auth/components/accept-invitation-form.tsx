'use client';

import { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { FormField } from '@/components/composed/form-field';
import { ErrorState, describeError } from '@/components/composed/error-state';
import { acceptInvitation, getInvitation } from '@/features/auth/api';
import { PasswordStrengthMeter } from '@/features/auth/components/password-strength-meter';
import { RecoveryCodes } from '@/features/auth/components/recovery-codes';
import { TotpEnrolment } from '@/features/auth/components/totp-enrolment';
import {
  makeAcceptInvitationSchema,
  type AcceptInvitationInput,
} from '@/features/auth/password-schema';

/**
 * Invitation acceptance: choose a password and enrol TOTP in one flow.
 *
 * The single flow is the point. Enrolment cannot be deferred to "later",
 * because an account holding a password and no second factor is precisely the
 * state the design refuses to allow (security.md section 5.3).
 */
export function AcceptInvitationForm({ token }: { token: string }) {
  const router = useRouter();
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  // Validated before the form renders, so an expired or already-consumed link
  // fails immediately rather than after the user has chosen a password.
  const invitation = useQuery({
    queryKey: ['invitation', token],
    queryFn: () => getInvitation(token),
    retry: false,
  });

  // Rebuilt once the lookup answers: react-hook-form reads its options on every
  // render, so the schema the resolver uses is the one holding the login rather
  // than the empty one this component first rendered with.
  const userInputs = useMemo(
    () => (invitation.data ? [invitation.data.login] : []),
    [invitation.data],
  );

  const form = useForm<AcceptInvitationInput>({
    resolver: zodResolver(makeAcceptInvitationSchema(userInputs)),
    defaultValues: { password: '', password_confirmation: '', totp_code: '' },
  });

  const password = form.watch('password');

  const accept = useMutation({
    mutationFn: (values: AcceptInvitationInput) =>
      acceptInvitation({
        token,
        password: values.password,
        totp_code: values.totp_code,
      }),
    onSuccess: (result) => setRecoveryCodes(result.recovery_codes),
  });

  if (invitation.isPending) {
    return <p className="text-sm text-muted-foreground">Checking this link…</p>;
  }

  if (invitation.isError) {
    // Unknown, expired, and already-consumed tokens are indistinguishable by
    // design; the backend returns one error for all three.
    return (
      <ErrorState
        title="This link is no longer valid"
        error="Invitation links expire and can only be used once. Ask an administrator for a new one."
      />
    );
  }

  // Reached only once the account is fully set up, so nobody can navigate away
  // mid-enrolment and lose the codes for an account that already works.
  if (recoveryCodes) {
    return (
      <RecoveryCodes
        codes={recoveryCodes}
        continueLabel="Go to the dashboard"
        onContinue={() => router.replace('/dashboard')}
      />
    );
  }

  return (
    <Form {...form}>
      <form
        className="space-y-6"
        onSubmit={form.handleSubmit((values) => accept.mutateAsync(values))}
      >
        <p className="text-sm text-muted-foreground">
          Setting up <span className="font-medium">{invitation.data.login}</span>
        </p>

        <FormField
          control={form.control}
          name="password"
          label="Password"
          type="password"
          autoComplete="new-password"
        />
        <PasswordStrengthMeter password={password} userInputs={userInputs} />

        <FormField
          control={form.control}
          name="password_confirmation"
          label="Confirm password"
          type="password"
          autoComplete="new-password"
        />

        {/*
          The token has to be on this URL. Nobody is signed in yet, so the
          endpoint has no session to identify the enrolment from, and an
          <img> cannot carry a request body. It is the same single-use token
          already in the address bar, and the endpoint returns the secret this
          form is displaying rather than issuing a second one.
        */}
        <TotpEnrolment
          enrolment={invitation.data}
          qrEndpoint={`/admin/invitations/totp-qr?token=${encodeURIComponent(token)}`}
        />

        <FormField
          control={form.control}
          name="totp_code"
          label="Code from your authenticator"
          description="Confirms the authenticator works before the account is created."
          autoComplete="one-time-code"
        />

        {accept.isError && (
          <p className="text-sm text-destructive">{describeError(accept.error)}</p>
        )}

        <Button type="submit" className="w-full" disabled={accept.isPending}>
          {accept.isPending ? 'Setting up...' : 'Create account'}
        </Button>
      </form>
    </Form>
  );
}
