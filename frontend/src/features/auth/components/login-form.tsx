'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { FormField } from '@/components/composed/form-field';
import { useLogin } from '@/features/auth/hooks/use-login';
import {
  loginStepOneSchema,
  loginStepTwoSchema,
  recoveryCodeLoginSchema,
  type LoginStepOneInput,
  type LoginStepTwoInput,
  type RecoveryCodeLoginInput,
} from '@/features/auth/schema';

function ErrorLine({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

/**
 * Password first, TOTP on a separate screen (frontend.md section 3). The error
 * message never distinguishes an unknown login from a wrong password; the hook
 * collapses every failure to one constant.
 */
export function LoginForm({ redirectTo = '/' }: { redirectTo?: string }) {
  const login = useLogin(redirectTo);
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);

  const passwordForm = useForm<LoginStepOneInput>({
    resolver: zodResolver(loginStepOneSchema),
    defaultValues: { login: '', password: '' },
  });

  const totpForm = useForm<LoginStepTwoInput>({
    resolver: zodResolver(loginStepTwoSchema),
    defaultValues: { code: '' },
  });

  const recoveryForm = useForm<RecoveryCodeLoginInput>({
    resolver: zodResolver(recoveryCodeLoginSchema),
    defaultValues: { recovery_code: '' },
  });

  if (login.step === 'password') {
    return (
      // `key` on each of the three branches below, because they occupy the
      // same position in the returned tree and differ only in which form's
      // `control` they carry. Without it React reconciles them as one
      // component and reuses the mounted `Controller`, whose registration
      // stays bound to the previous form: after the password step the
      // verification-code input rendered, accepted focus, and dropped every
      // keystroke — typed characters never appeared, and the submitted value
      // was always empty. See login-form.test.tsx.
      <Form key="password" {...passwordForm}>
        <form
          className="space-y-4"
          onSubmit={passwordForm.handleSubmit(login.submitPassword)}
        >
          <FormField
            control={passwordForm.control}
            name="login"
            label="Login"
            type="email"
            autoComplete="username"
            placeholder="you@example.org"
          />
          <FormField
            control={passwordForm.control}
            name="password"
            label="Password"
            type="password"
            autoComplete="current-password"
          />
          <ErrorLine message={login.error} />
          <Button type="submit" className="w-full" disabled={login.pending}>
            {login.pending ? 'Checking...' : 'Continue'}
          </Button>
          {/* There is no self-service reset, and there is deliberately no link
              here pretending otherwise: a reset link is issued by an
              administrator from the Users screen and delivered out of band,
              because an unauthenticated endpoint that emails one would be an
              account-enumeration oracle. Saying nothing left someone who had
              forgotten their password on a screen with no visible way out. */}
          <p className="text-center text-xs text-muted-foreground">
            Forgotten your password? An administrator issues a single-use reset
            link; there is no self-service reset. Ask whoever set up your
            account.
          </p>
        </form>
      </Form>
    );
  }

  if (useRecoveryCode) {
    return (
      <Form key="recovery" {...recoveryForm}>
        <form
          className="space-y-4"
          onSubmit={recoveryForm.handleSubmit(login.submitRecoveryCode)}
        >
          <FormField
            control={recoveryForm.control}
            name="recovery_code"
            label="Recovery code"
            autoComplete="one-time-code"
            description="Single use. Using one leaves you with fewer."
          />
          <ErrorLine message={login.error} />
          <Button type="submit" className="w-full" disabled={login.pending}>
            {login.pending ? 'Checking...' : 'Sign in'}
          </Button>
          <Button
            type="button"
            variant="link"
            className="w-full"
            onClick={() => setUseRecoveryCode(false)}
          >
            Use the authenticator app instead
          </Button>
        </form>
      </Form>
    );
  }

  return (
    <Form key="totp" {...totpForm}>
      <form
        className="space-y-4"
        onSubmit={totpForm.handleSubmit(login.submitTotp)}
      >
        <FormField
          control={totpForm.control}
          name="code"
          label="Verification code"
          autoComplete="one-time-code"
          placeholder="000000"
          description="Six digits from your authenticator app."
        />
        <ErrorLine message={login.error} />
        <Button type="submit" className="w-full" disabled={login.pending}>
          {login.pending ? 'Checking...' : 'Sign in'}
        </Button>
        <div className="flex justify-between">
          <Button
            type="button"
            variant="link"
            size="sm"
            onClick={() => {
              setUseRecoveryCode(false);
              login.restart();
              passwordForm.reset();
            }}
          >
            Start over
          </Button>
          <Button
            type="button"
            variant="link"
            size="sm"
            onClick={() => setUseRecoveryCode(true)}
          >
            Lost your authenticator?
          </Button>
        </div>
      </form>
    </Form>
  );
}
