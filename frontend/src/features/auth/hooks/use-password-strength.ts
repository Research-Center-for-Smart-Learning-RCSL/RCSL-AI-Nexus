'use client';

import { useMemo } from 'react';

import { scorePassword, type PasswordStrength } from '@/features/auth/password-schema';

/**
 * zxcvbn is not cheap on long inputs, so the result is memoised on the exact
 * string. The threshold matches the backend's, so the meter never shows green
 * for something the API would reject.
 */
export function usePasswordStrength(password: string): PasswordStrength {
  return useMemo(() => scorePassword(password), [password]);
}

