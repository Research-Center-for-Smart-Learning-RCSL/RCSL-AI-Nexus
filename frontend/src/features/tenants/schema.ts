import { z } from 'zod';

/**
 * Tenants are the isolation boundary for users, keys, usage and audit
 * (security.md section 7.3). Managing them is a platform operation, so this is
 * an admin-only screen. Creating a tenant also mints its first administrator's
 * invitation, since a tenant with no admin cannot be populated.
 */

export const tenantSchema = z.object({
  id: z.string(),
  name: z.string(),
  created_at: z.string().nullable(),
});
export type Tenant = z.infer<typeof tenantSchema>;

export const tenantListSchema = z.array(tenantSchema);

export const createTenantSchema = z.object({
  name: z.string().min(1, 'Required').max(128),
  first_admin_login: z.string().email('Enter a valid email.'),
  first_admin_display_name: z.string().min(1, 'Required').max(120),
});
export type CreateTenantInput = z.infer<typeof createTenantSchema>;

/** Mirrors the invitation shape the backend returns; only the url is used. */
const invitationSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  url: z.string().nullable(),
  expires_at: z.string(),
  consumed_at: z.string().nullable().optional(),
});

export const createTenantResponseSchema = z.object({
  tenant: tenantSchema,
  invitation: invitationSchema,
});
export type CreateTenantResponse = z.infer<typeof createTenantResponseSchema>;
