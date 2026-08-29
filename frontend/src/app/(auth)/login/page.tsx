'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { sameOriginPath } from '@/lib/safe-redirect';
import { LoginForm } from '@/features/auth/components/login-form';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LoginEntryTransition } from '@/components/composed/entry-transition';

/**
 * Public entrance only. The tailnet entrance never reaches this route: there
 * identity arrives as a header and there is nothing to sign in to.
 */
function LoginPageInner() {
  const params = useSearchParams();
  const redirectTo = sameOriginPath(params.get('next'));

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>
            Accounts are created by an administrator. There is no self-registration.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <LoginForm redirectTo={redirectTo} />
        </CardContent>
      </Card>
      <LoginEntryTransition bypass={params.has('next')} />
    </>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageInner />
    </Suspense>
  );
}
