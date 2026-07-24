'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { LoginForm } from '@/features/auth/components/login-form';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

/**
 * Public entrance only. The tailnet entrance never reaches this route: there
 * identity arrives as a header and there is nothing to sign in to.
 */
function LoginPageInner() {
  const params = useSearchParams();
  // Only ever a same-origin path. An absolute URL here would make this an
  // open redirect, which is a convenient phishing primitive on a login page.
  const requested = params.get('next') ?? '/';
  const redirectTo = requested.startsWith('/') && !requested.startsWith('//') ? requested : '/';

  return (
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
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageInner />
    </Suspense>
  );
}
