'use client';

/**
 * Replacing your authenticator, for a new phone or a lost one.
 *
 * Three steps, in this order for a reason the use case enforces:
 *
 *  1. Prove the current password. Swapping the second factor is swapping a
 *     bearer credential, so a hijacked session alone must not be enough.
 *  2. Scan the candidate secret. It lives in a server-side cache for minutes
 *     and is never written to the user row, so abandoning this screen — or
 *     closing the tab at exactly the wrong moment — leaves the working
 *     authenticator intact.
 *  3. Confirm with a code from the new app. Only then is the secret swapped in,
 *     which is also when a fresh set of recovery codes is issued and every other
 *     session is signed out.
 *
 * The recovery codes replace the previous set outright. That is stated before
 * the flow starts, because someone re-enrolling a working authenticator on a
 * second device would otherwise invalidate codes they still have on paper.
 */

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation } from '@tanstack/react-query';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Form } from '@/components/ui/form';
import { FormField } from '@/components/composed/form-field';
import { describeError } from '@/components/composed/error-state';
import { RecoveryCodes } from '@/features/auth/components/recovery-codes';
import { TotpEnrolment } from '@/features/auth/components/totp-enrolment';
import { beginTotpReenrolment, confirmTotpReenrolment } from '@/features/auth/api';
import type { Enrolment } from '@/features/auth/schema';

const beginSchema = z.object({
  current_password: z.string().min(1, 'Required'),
});
type BeginInput = z.infer<typeof beginSchema>;

const confirmSchema = z.object({
  code: z.string().regex(/^\d{6}$/, 'Six digits.'),
});
type ConfirmInput = z.infer<typeof confirmSchema>;

export function TotpReenrolmentCard() {
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  const beginForm = useForm<BeginInput>({
    resolver: zodResolver(beginSchema),
    defaultValues: { current_password: '' },
  });

  const confirmForm = useForm<ConfirmInput>({
    resolver: zodResolver(confirmSchema),
    defaultValues: { code: '' },
  });

  const begin = useMutation({
    mutationFn: (values: BeginInput) => beginTotpReenrolment(values),
    onSuccess: (result) => {
      setEnrolment(result);
      // The password is no longer needed and should not sit in memory behind a
      // screen that has moved on from asking for it.
      beginForm.reset();
    },
  });

  const confirm = useMutation({
    mutationFn: (values: ConfirmInput) => confirmTotpReenrolment(values),
    onSuccess: (result) => setRecoveryCodes(result.recovery_codes),
  });

  function cancel() {
    setEnrolment(null);
    confirmForm.reset();
    confirm.reset();
    begin.reset();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Authenticator</CardTitle>
        <CardDescription>
          Replace the six-digit code generator, for a new phone or a lost one.
          Confirming issues a new set of recovery codes and invalidates the old
          set, and signs out every other session.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {recoveryCodes ? (
          <RecoveryCodes
            codes={recoveryCodes}
            continueLabel="Done"
            onContinue={() => {
              setRecoveryCodes(null);
              cancel();
            }}
          />
        ) : enrolment ? (
          <div className="space-y-4">
            <TotpEnrolment
              enrolment={enrolment}
              // Session-authenticated and same-origin: unlike the invitation
              // screen there is no token to carry, because the endpoint knows
              // who is asking.
              qrEndpoint="/admin/me/totp/qr"
            />

            <Form {...confirmForm}>
              <form
                className="space-y-4"
                onSubmit={confirmForm.handleSubmit((values) =>
                  confirm.mutateAsync(values),
                )}
              >
                <FormField
                  control={confirmForm.control}
                  name="code"
                  label="Code from the new authenticator"
                  autoComplete="one-time-code"
                  placeholder="000000"
                  description="The old authenticator keeps working until this succeeds."
                />

                {confirm.isError ? (
                  <p role="alert" className="text-sm text-destructive">
                    {describeError(confirm.error)}
                  </p>
                ) : null}

                <div className="flex gap-2">
                  <Button type="submit" disabled={confirm.isPending}>
                    {confirm.isPending ? 'Confirming...' : 'Confirm and replace'}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={confirm.isPending}
                    onClick={cancel}
                  >
                    Cancel
                  </Button>
                </div>
              </form>
            </Form>
          </div>
        ) : (
          <Form {...beginForm}>
            <form
              className="space-y-4"
              onSubmit={beginForm.handleSubmit((values) =>
                begin.mutateAsync(values),
              )}
            >
              <FormField
                control={beginForm.control}
                name="current_password"
                label="Current password"
                type="password"
                autoComplete="current-password"
                description="Proves it is you before a new secret is issued."
              />

              {begin.isError ? (
                <p role="alert" className="text-sm text-destructive">
                  {describeError(begin.error)}
                </p>
              ) : null}

              <Button type="submit" disabled={begin.isPending}>
                {begin.isPending ? 'Starting...' : 'Replace authenticator'}
              </Button>
            </form>
          </Form>
        )}
      </CardContent>
    </Card>
  );
}
