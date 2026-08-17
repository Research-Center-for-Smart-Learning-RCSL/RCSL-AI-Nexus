/**
 * Generated from the backend role map. Do not edit.
 *
 *     scripts/generate-api-types.sh
 *
 * What each role holds, taken from `adapters/authz/role_authorization.py`
 * through its public `scopes_for`.
 *
 * This file exists because a hand-written copy of that map drifted twice in one
 * day, and each time the tests kept passing while asserting a navigation no
 * real role is shown. A generated copy cannot drift: CI regenerates it and
 * fails if the committed result differs.
 *
 * **Consuming this in a test does not weaken the test.** What a role holds is
 * now followed rather than restated; what a role can *see* is still asserted
 * explicitly, so a scope change that alters the navigation fails loudly, with
 * the expected list of links beside it.
 */

/** Every scope the backend defines. */
export const SCOPE_NAMES = [
  'api_key:read_own',
  'api_key:write_any',
  'api_key:write_own',
  'chat:use',
  'knowledge:read',
  'knowledge:write',
  'logs:read',
  'model:read',
  'model:write',
  'node:read',
  'node:write',
  'prompt:read',
  'prompt:write',
  'prompt_log:read',
  'refusal:read_all',
  'refusal:read_own',
  'retention:write',
  'routing:read',
  'routing:write',
  'tenant:read',
  'tenant:write',
  'usage:read_all',
  'usage:read_own',
  'user:read',
  'user:write',
] as const;

/**
 * A scope name known at build time.
 *
 * Distinct from `ScopeName`, which stays `string` because it types what the
 * server sends and this application must not claim to know that
 * exhaustively. Use this one wherever a scope is *authored* — a nav entry's
 * `requires`, a cross-reference — so a typo is a compile error rather than
 * an entry that silently never renders.
 */
export type KnownScope = (typeof SCOPE_NAMES)[number];

/** Roles as the backend spells them, including the non-human `service`. */
export type GeneratedRole =
  | 'admin'
  | 'tenant_admin'
  | 'operator'
  | 'curator'
  | 'auditor'
  | 'user'
  | 'service';

export const ROLE_SCOPES: Record<GeneratedRole, readonly KnownScope[]> = {
  'admin': [
    'api_key:read_own',
    'api_key:write_any',
    'api_key:write_own',
    'chat:use',
    'knowledge:read',
    'knowledge:write',
    'logs:read',
    'model:read',
    'model:write',
    'node:read',
    'node:write',
    'prompt:read',
    'prompt:write',
    'prompt_log:read',
    'refusal:read_all',
    'refusal:read_own',
    'retention:write',
    'routing:read',
    'routing:write',
    'tenant:read',
    'tenant:write',
    'usage:read_all',
    'usage:read_own',
    'user:read',
    'user:write',
  ],
  'tenant_admin': [
    'api_key:read_own',
    'api_key:write_any',
    'api_key:write_own',
    'chat:use',
    'knowledge:read',
    'knowledge:write',
    'logs:read',
    'model:read',
    'node:read',
    'prompt:read',
    'prompt:write',
    'refusal:read_all',
    'refusal:read_own',
    'routing:read',
    'tenant:read',
    'usage:read_all',
    'usage:read_own',
    'user:read',
    'user:write',
  ],
  'operator': [
    'api_key:read_own',
    'api_key:write_own',
    'chat:use',
    'knowledge:read',
    'logs:read',
    'model:read',
    'model:write',
    'node:read',
    'node:write',
    'prompt:read',
    'refusal:read_all',
    'refusal:read_own',
    'routing:read',
    'routing:write',
    'tenant:read',
    'usage:read_all',
    'usage:read_own',
    'user:read',
  ],
  'curator': [
    'api_key:read_own',
    'api_key:write_own',
    'chat:use',
    'knowledge:read',
    'knowledge:write',
    'prompt:read',
    'prompt:write',
    'refusal:read_own',
    'usage:read_own',
  ],
  'auditor': [
    'api_key:read_own',
    'chat:use',
    'knowledge:read',
    'logs:read',
    'model:read',
    'node:read',
    'prompt:read',
    'refusal:read_all',
    'refusal:read_own',
    'routing:read',
    'tenant:read',
    'usage:read_all',
    'usage:read_own',
    'user:read',
  ],
  'user': [
    'api_key:read_own',
    'api_key:write_own',
    'chat:use',
    'prompt:read',
    'refusal:read_own',
    'usage:read_own',
  ],
  'service': [
    'chat:use',
    'usage:read_own',
  ],
};

/** Held by `admin` and no other role. */
export const ADMIN_ONLY_SCOPES = [
  'prompt_log:read',
  'retention:write',
  'tenant:write',
] as const;
