import type { AuthMode } from './types';

/**
 * How the reader was identified, in the reader's terms.
 *
 * The shell showed the wire value — `tailnet`, `local`, `dev` — beside the
 * product name, which names an implementation rather than a fact about the
 * current session. What the badge is for is telling someone which entrance
 * they came in by, because that decides whether a password and an
 * authenticator apply to them at all.
 */
export const AUTH_MODE_LABELS: Record<AuthMode, string> = {
  tailnet: 'Private network',
  local: 'Password sign-in',
  dev: 'Development',
};

export function authModeLabel(mode: AuthMode | null): string {
  return mode ? AUTH_MODE_LABELS[mode] : 'Unknown entrance';
}
