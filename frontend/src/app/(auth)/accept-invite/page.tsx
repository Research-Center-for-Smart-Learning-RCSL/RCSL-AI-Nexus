'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { AcceptInvitationForm } from '@/features/auth/components/accept-invitation-form';
import { ErrorState } from '@/components/composed/error-state';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

function AcceptInviteInner() {
  const token = useSearchParams().get('token');

  return (
    <Card>
      <CardHeader>
        <CardTitle>Set up your account</CardTitle>
        <CardDescription>
          Choose a password and enrol an authenticator. Both are required.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {token ? (
          <AcceptInvitationForm token={token} />
        ) : (
          <ErrorState
            title="This link is incomplete"
            error="Open the invitation link exactly as it was sent to you."
          />
        )}
      </CardContent>
    </Card>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={null}>
      <AcceptInviteInner />
    </Suspense>
  );
}
