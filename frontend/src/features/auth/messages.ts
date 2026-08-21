/**
 * Authentication copy that is a security control, not wording.
 *
 * The backend runs a dummy hash verification when no user matches, so that an
 * unknown login and a wrong password are indistinguishable in both response and
 * timing (backend.md section 7, security.md section 5.3). A friendlier UI
 * message such as "no account with that email" would hand back exactly the
 * enumeration oracle the backend spent effort removing.
 *
 * One constant, used for every failure of the password step, whatever the
 * backend's status code. Do not add a second.
 */
export const CREDENTIALS_REJECTED =
  'That login and password combination was not accepted.';

/**
 * Same reasoning for the second step. Whether the code was wrong, expired, or
 * already used within its window, the user is told one thing.
 */
export const SECOND_FACTOR_REJECTED =
  'That verification code was not accepted.';

export const RATE_LIMITED =
  'Too many attempts. Wait a moment before trying again.';

/**
 * Shown on the tailnet entrance when a request comes back 401. There is no
 * session to renew, so the only useful action is to check the connection.
 */
export const TAILSCALE_CONNECTION_LOST =
  'Tailscale connection lost. Check that you are connected to the tailnet, then retry.';

export const RECOVERY_CODES_WARNING =
  'These are shown once and cannot be retrieved afterwards. Store them separately from the password they protect.';
