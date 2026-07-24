'use client';

/**
 * The two-step login state machine (frontend.md section 3).
 *
 * All failures of a step collapse to one constant message. See
 * features/auth/messages.ts for why that is a control rather than copy.
 */

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api-client';
import { ME_QUERY_KEY } from '@/lib/session';
import {
  loginWithPassword,
  loginWithRecoveryCode,
  loginWithTotp,
} from '@/features/auth/api';
import {
  CREDENTIALS_REJECTED,
  RATE_LIMITED,
  SECOND_FACTOR_REJECTED,
} from '@/features/auth/messages';

export type LoginStep = 'password' | 'totp';

export function useLogin(redirectTo = '/') {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [step, setStep] = useState<LoginStep>('password');
  const [challenge, setChallenge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  /**
   * 429 is disclosed because it is not an oracle: it tells the caller about
   * their own request rate, not about whether an account exists. Everything
   * else, including a 404, becomes the one message.
   */
  const collapse = useCallback((caught: unknown, fallback: string) => {
    if (caught instanceof ApiError && caught.status === 429) return RATE_LIMITED;
    return fallback;
  }, []);

  const submitPassword = useCallback(
    async (values: { login: string; password: string }) => {
      setPending(true);
      setError(null);
      try {
        const result = await loginWithPassword(values);
        setChallenge(result.challenge);
        setStep('totp');
      } catch (caught) {
        setError(collapse(caught, CREDENTIALS_REJECTED));
      } finally {
        setPending(false);
      }
    },
    [collapse],
  );

  const finish = useCallback(async () => {
    // The session cookie is set by the response; refetch identity through the
    // normal path rather than trusting anything the login response said.
    await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
    router.replace(redirectTo);
  }, [queryClient, redirectTo, router]);

  const submitTotp = useCallback(
    async (values: { code: string }) => {
      if (!challenge) return;
      setPending(true);
      setError(null);
      try {
        await loginWithTotp({ challenge, code: values.code });
        await finish();
      } catch (caught) {
        setError(collapse(caught, SECOND_FACTOR_REJECTED));
      } finally {
        setPending(false);
      }
    },
    [challenge, collapse, finish],
  );

  const submitRecoveryCode = useCallback(
    async (values: { recovery_code: string }) => {
      if (!challenge) return;
      setPending(true);
      setError(null);
      try {
        await loginWithRecoveryCode({
          challenge,
          recovery_code: values.recovery_code,
        });
        await finish();
      } catch (caught) {
        setError(collapse(caught, SECOND_FACTOR_REJECTED));
      } finally {
        setPending(false);
      }
    },
    [challenge, collapse, finish],
  );

  const restart = useCallback(() => {
    setStep('password');
    setChallenge(null);
    setError(null);
  }, []);

  return {
    step,
    error,
    pending,
    submitPassword,
    submitTotp,
    submitRecoveryCode,
    restart,
  };
}
