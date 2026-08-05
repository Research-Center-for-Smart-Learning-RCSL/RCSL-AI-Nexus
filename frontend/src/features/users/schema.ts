import { z } from 'zod';

/**
 * Mirrors ARCHITECTURE.md section 2.6. Credential columns never leave the
 * backend, so `password_hash` and `totp_secret` have no representation here;
 * the UI only learns whether they are set.
 */

/**
 * Mirrors `Role` in the backend, minus `service`, which belongs to an API key
 * and is never assignable to a person — `ASSIGNABLE_ROLES` omits it there for
 * the same reason.
 *
 * Order is widest authority first, and it is a presentation choice rather than
 * a ranking: these do not nest. A `curator` may rewrite the knowledge base an
 * `operator` cannot touch, and an `operator` may restart a node a
 * `tenant_admin` cannot.
 */
export const roleSchema = z.enum([
  'admin',
  'tenant_admin',
  'operator',
  'curator',
  'auditor',
  'user',
]);
export type Role = z.infer<typeof roleSchema>;

/** One entry of `GET /admin/roles`. The scope list is generated from the same
 *  table the backend enforces, so this screen cannot describe a permission the
 *  platform does not grant. */
export const roleCatalogueEntrySchema = z.object({
  role: roleSchema,
  scopes: z.array(z.string()),
});
export const roleCatalogueSchema = z.array(roleCatalogueEntrySchema);
export type RoleCatalogueEntry = z.infer<typeof roleCatalogueEntrySchema>;

export const userSchema = z.object({
  id: z.string(),
  login: z.string(),
  display_name: z.string(),
  tailscale_login: z.string().nullable(),
  /** Derived server-side from `password_hash`; the hash itself is never sent. */
  has_local_credentials: z.boolean(),
  /** Always true when local credentials exist: TOTP cannot be deferred. */
  has_totp: z.boolean(),
  role: roleSchema,
  debug_logging_until: z.string().nullable(),
  /**
   * Nullable because the API says so, and the API is right: the column is
   * `NOT NULL`, but an entity that has been constructed and not yet read back
   * carries no timestamp. That is not hypothetical — `IssueInvitation` returns
   * the account it just created, and returning the unsaved entity once made
   * this very field throw *after* the account existed, taking the invitation
   * link with it, which is the only copy there is. The read-back that fixed it
   * lives in the use case; this stops the same shape being fatal again.
   */
  created_at: z.string().nullable(),
});
export type User = z.infer<typeof userSchema>;

export const userListSchema = z.array(userSchema);

/**
 * Accounts are invitation only; there is no self-registration and the platform
 * never transmits a credential (security.md section 5.4). Creating a user
 * therefore takes a login and a role, nothing else.
 */
export const createUserSchema = z.object({
  login: z.email('Enter a valid email address.'),
  display_name: z.string().min(1, 'Required').max(120),
  role: roleSchema,
});
export type CreateUserInput = z.infer<typeof createUserSchema>;

export const updateUserSchema = z.object({
  display_name: z.string().min(1).max(120).optional(),
  role: roleSchema.optional(),
});
export type UpdateUserInput = z.infer<typeof updateUserSchema>;

/**
 * The invitation link is returned exactly once, at creation. The administrator
 * delivers it out of band; nothing is emailed by the platform.
 */
export const invitationSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  /**
   * Full single-use URL. Present only in the response that issued it.
   *
   * `nullish`, not `optional`: the backend field is `str | None`, and pydantic
   * serialises that as an explicit `"url": null` rather than leaving the key
   * out — so `optional()` alone accepts the shape nobody sends and rejects the
   * one everybody does. Every consumer already guards with `?? null` or a
   * truthiness check, so this was the only layer that would have thrown, on the
   * one response whose contents cannot be fetched again.
   */
  url: z.string().nullish(),
  expires_at: z.string(),
  consumed_at: z.string().nullable(),
});
export type Invitation = z.infer<typeof invitationSchema>;

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Platform administrator',
  tenant_admin: 'Tenant administrator',
  operator: 'Operator',
  curator: 'Knowledge curator',
  auditor: 'Auditor',
  user: 'User',
};

/**
 * What each role is *for*, in one line, and what it deliberately cannot do.
 *
 * The picker offered role names and nothing else until 2026-08-04, so choosing
 * between `operator` and `tenant_admin` meant reading the source. This is the
 * prose half; the exact scope list beside it comes from `GET /admin/roles` and
 * is generated from the authorization table, so the wording here can go out of
 * date without the permissions display going wrong with it.
 */
export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  admin:
    'Everything, across every tenant. The only role that can create a tenant — the boundary all the others are confined by.',
  tenant_admin:
    'Full authority inside their own tenant: its people, its API keys, its knowledge base. Reads the fleet but cannot change it, and cannot create a tenant.',
  operator:
    'Runs the fleet — models, nodes, routing policies — and grants nobody access. Deliberately cannot invite users, change roles, or issue keys for anyone else.',
  curator:
    'Maintains the knowledge base and nothing else. Separate because knowledge documents shape what the models answer, which is authority worth granting on purpose.',
  auditor:
    'Reads everything and changes nothing — usage, logs, models, nodes, users. Holds no write at all, not even to their own API keys.',
  user: 'Uses the chat UI, manages their own API keys, sees their own usage.',
};

/**
 * Plain-language names for the scopes the catalogue returns, so the detail is
 * readable by whoever is choosing a role rather than only by whoever wrote it.
 *
 * A scope with no entry falls back to its own identifier: an unnamed permission
 * should still be *shown*, because omitting it would understate what a role
 * grants, which is the one direction this screen must not be wrong in.
 */
export const SCOPE_LABELS: Record<string, string> = {
  'chat:use': 'Use the chat UI',
  'model:read': 'View models',
  'model:write': 'Load, unload and register models',
  'routing:read': 'View routing policies',
  'routing:write': 'Change routing policies',
  'api_key:read_own': 'View their own API keys',
  'api_key:write_own': 'Create and revoke their own API keys',
  'api_key:write_any': "Create and revoke anyone's API keys",
  'user:read': 'View accounts',
  'user:write': 'Invite, edit and remove accounts',
  'node:read': 'View nodes',
  'node:write': 'Manage nodes',
  'tenant:read': 'View tenants',
  'tenant:write': 'Create and change tenants',
  'usage:read_own': 'See their own usage',
  'usage:read_all': "See everyone's usage",
  'logs:read': 'Read the audit log',
  'knowledge:read': 'Read the knowledge base',
  'knowledge:write': 'Add and remove knowledge documents',
  'prompt:read': 'See the tenant\'s prompt templates',
  'prompt:write': 'Write and remove prompt templates',
};
