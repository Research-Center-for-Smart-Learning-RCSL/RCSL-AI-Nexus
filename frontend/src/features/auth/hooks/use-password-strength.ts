'use client';

import { useMemo } from 'react';

import { scorePassword, type PasswordStrength } from '@/features/auth/password-schema';

/**
 * zxcvbn is not cheap on long inputs, so the result is memoised on the exact
 * string. The threshold matches the backend's, so the meter never shows green
 * for something the API would reject.
 */
export function usePasswordStrength(
  password: string,
  userInputs: readonly string[] = [],
): PasswordStrength {
  // Joined for the dependency list: the array is rebuilt on every render by
  // every caller, so identity would defeat the memo the comment above is about.
  const key = userInputs.join('\u0000');
  return useMemo(() => scorePassword(password, key ? key.split('\u0000') : []), [password, key]);
}

