'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { ResetPasswordForm } from '@/features/auth/components/reset-password-form';
import { ErrorState } from '@/components/composed/error-state';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

function ResetPasswordInner() {
  const token = useSearchParams().get('token');

  return (
    <Card>
      <CardHeader>
        <CardTitle>Choose a new password</CardTitle>
        <CardDescription>
          Your authenticator is unchanged. You will still need it to sign in.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {token ? (
          <ResetPasswordForm token={token} />
        ) : (
          <ErrorState
            title="This link is incomplete"
            error="Open the reset link exactly as it was sent to you."
          />
        )}
      </CardContent>
    </Card>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordInner />
    </Suspense>
  );
}
