import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { LoginForm } from '@/features/auth/components/login-form';

/**
 * The second step of sign-in, which had no test at all and did not work.
 *
 * Two independent defects, either of which alone makes the step impassable.
 * Each assertion below fails against exactly one of them.
 *
 * 1. **The field dropped every keystroke.** The three branches of this
 *    component — password, TOTP, recovery code — are returned from the same
 *    position and differ only in which form's `control` they carry, so React
 *    reconciled them as one component and reused the mounted `Controller`,
 *    whose registration stayed bound to the previous form. The input rendered
 *    and took focus, and nothing a user typed ever appeared or was submitted.
 *    Fixed with a `key` per branch. This took the recovery-code route down
 *    with it, so there was no working second factor at all.
 * 2. **The submission was a dead end.** `loginStepTwoSchema` required
 *    `challenge`, which is not a form field — it lives in `useLogin` state and
 *    is attached by `submitTotp` on the way to the API. The resolver therefore
 *    rejected the only shape the form could hold, `handleSubmit` never called
 *    the hook, and the error was attached to a name nothing renders: no
 *    request, no message, no visible change.
 *
 * Both survived because nothing under `components/` was tested, and because
 * neither is visible from the entrance: until 2026-08-04 no request reached
 * this application at all, so nobody had got as far as the second step.
 */

const loginWithPassword = vi.fn();
const loginWithTotp = vi.fn();
const loginWithRecoveryCode = vi.fn();

vi.mock('@/features/auth/api', () => ({
  loginWithPassword: (...args: unknown[]) => loginWithPassword(...args),
  loginWithTotp: (...args: unknown[]) => loginWithTotp(...args),
  loginWithRecoveryCode: (...args: unknown[]) => loginWithRecoveryCode(...args),
}));

const replace = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
}));

function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function reachTheSecondStep() {
  const user = userEvent.setup();
  loginWithPassword.mockResolvedValue({ challenge: 'ch_abc', next: 'totp' });
  render(<LoginForm />, { wrapper: Wrapper });

  await user.type(screen.getByLabelText('Login'), 'someone@ntnu.edu.tw');
  await user.type(screen.getByLabelText('Password'), 'correct horse');
  await user.click(screen.getByRole('button', { name: 'Continue' }));

  await screen.findByLabelText('Verification code');
  return user;
}

beforeEach(() => {
  loginWithPassword.mockReset();
  loginWithTotp.mockReset();
  loginWithRecoveryCode.mockReset();
  replace.mockReset();
});

describe('the second step of sign-in', () => {
  it('sends the code, with the challenge the hook is holding', async () => {
    const user = await reachTheSecondStep();
    loginWithTotp.mockResolvedValue(undefined);

    await user.type(screen.getByLabelText('Verification code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() =>
      expect(loginWithTotp).toHaveBeenCalledWith({
        challenge: 'ch_abc',
        code: '123456',
      }),
    );
  });

  it('shows the typed code in the field', async () => {
    const user = await reachTheSecondStep();
    const field = screen.getByLabelText('Verification code');

    await user.type(field, '123456');

    expect((field as HTMLInputElement).value).toBe('123456');
  });

  it('refuses a code that is not six digits, and says so', async () => {
    const user = await reachTheSecondStep();

    await user.type(screen.getByLabelText('Verification code'), '12345');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Six digits.')).toBeInTheDocument();
    expect(loginWithTotp).not.toHaveBeenCalled();
  });

  it('collapses a rejected code to the one message', async () => {
    const user = await reachTheSecondStep();
    loginWithTotp.mockRejectedValue(new Error('nope'));

    await user.type(screen.getByLabelText('Verification code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(
      await screen.findByText('That verification code was not accepted.'),
    ).toBeInTheDocument();
  });

  it('still offers the recovery-code route, which was the only one that worked', async () => {
    const user = await reachTheSecondStep();
    loginWithRecoveryCode.mockResolvedValue(undefined);

    await user.click(screen.getByRole("button", { name: /Lost your authenticator/i }));
    await user.type(screen.getByLabelText(/recovery code/i), 'abcd-efgh');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() =>
      expect(loginWithRecoveryCode).toHaveBeenCalledWith({
        challenge: 'ch_abc',
        recovery_code: 'abcd-efgh',
      }),
    );
  });
});
