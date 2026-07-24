import { z } from 'zod';

/**
 * Mirrors ARCHITECTURE.md section 2.6. Credential columns never leave the
 * backend, so `password_hash` and `totp_secret` have no representation here;
 * the UI only learns whether they are set.
 */

export const roleSchema = z.enum(['admin', 'user']);
export type Role = z.infer<typeof roleSchema>;

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
  created_at: z.string(),
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
  /** Full single-use URL. Present only in the creation response. */
  url: z.string().optional(),
  expires_at: z.string(),
  consumed_at: z.string().nullable(),
});
export type Invitation = z.infer<typeof invitationSchema>;

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Administrator',
  user: 'User',
};
