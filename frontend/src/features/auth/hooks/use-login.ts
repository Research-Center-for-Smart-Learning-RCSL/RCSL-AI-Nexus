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
   * Everything that can fail the password step reports the one message,
   * including 429.
   *
   * Showing "too many attempts" there was an account-enumeration oracle, and a
   * clean binary one. Rate limiting is specified per source address *and per
   * account* (security.md section 5.3), so the per-account bucket can only
   * trip for a login that exists. An attacker below the address limit submits
   * junk passwords for a candidate address and watches for the message to
   * change: for a real account it eventually does, for a nonexistent one it
   * never can. That undoes the dummy-hash work the backend does to make the
   * two indistinguishable.
   *
   * The second step is different: reaching it already required the password,
   * so there is nothing left to enumerate and the rate-limit message is
   * genuinely useful there.
   */
  const collapseSecondStep = useCallback((caught: unknown, fallback: string) => {
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
      } catch {
        setError(CREDENTIALS_REJECTED);
      } finally {
        setPending(false);
      }
    },
    [],
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
        setError(collapseSecondStep(caught, SECOND_FACTOR_REJECTED));
      } finally {
        setPending(false);
      }
    },
    [challenge, collapseSecondStep, finish],
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
        setError(collapseSecondStep(caught, SECOND_FACTOR_REJECTED));
      } finally {
        setPending(false);
      }
    },
    [challenge, collapseSecondStep, finish],
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
