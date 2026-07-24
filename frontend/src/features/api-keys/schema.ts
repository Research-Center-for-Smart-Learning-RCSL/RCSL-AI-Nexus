import { z } from 'zod';

import { capabilitySchema } from '@/features/models/schema';

/**
 * Mirrors security.md section 4.2. The plaintext key is never stored and is
 * returned exactly once, at issue; `key_id` is the lookup handle that is safe
 * to show in the UI and in logs because it reveals nothing about the secret.
 */

export const apiKeySchema = z.object({
  key_id: z.string(),
  name: z.string(),
  scopes: z.array(capabilitySchema),
  rate_limit_rpm: z.number().int().nonnegative(),
  quota_tokens_per_day: z.number().int().nonnegative(),
  allowed_cidrs: z.array(z.string()),
  expires_at: z.string(),
  owner_id: z.string(),
  owner_display: z.string().nullable(),
  revoked_at: z.string().nullable(),
  created_at: z.string(),
  last_used_at: z.string().nullable(),
});
export type ApiKey = z.infer<typeof apiKeySchema>;

export const apiKeyListSchema = z.array(apiKeySchema);

/** IPv4 or IPv6 with a prefix length. The server re-validates. */
const CIDR_PATTERN = /^([0-9.]+|[0-9a-fA-F:]+)\/\d{1,3}$/;

export const createApiKeySchema = z.object({
  name: z.string().min(1, 'Required').max(80),
  scopes: z.array(capabilitySchema).min(1, 'Choose at least one capability.'),
  rate_limit_rpm: z.coerce.number().int().positive(),
  quota_tokens_per_day: z.coerce.number().int().positive(),
  allowed_cidrs: z
    .array(z.string().regex(CIDR_PATTERN, 'Expected an address with a prefix.'))
    .default([]),
  // Expiry is mandatory by design: it forces rotation. There is no "never".
  expires_at: z.string().min(1, 'An expiry is required.'),
  owner_id: z.string().min(1, 'Required'),
});
/**
 * Input and output types differ here and must be kept apart: `z.coerce`
 * accepts the string a number input actually produces, and `.default()` makes
 * a field optional before parsing. `z.infer` is the output type, so using it
 * for the form would claim the form holds values it only holds after parsing.
 * react-hook-form takes both, which is what keeps the resolver assignable.
 */
export type CreateApiKeyInput = z.input<typeof createApiKeySchema>;
export type CreateApiKeyValues = z.output<typeof createApiKeySchema>;

/** Issue response. `plaintext` exists here and nowhere else, ever. */
export const issuedApiKeySchema = z.object({
  key: apiKeySchema,
  plaintext: z.string(),
});
export type IssuedApiKey = z.infer<typeof issuedApiKeySchema>;

export const DEFAULT_EXPIRY_DAYS = 90;

export function defaultExpiry(): string {
  const date = new Date();
  date.setDate(date.getDate() + DEFAULT_EXPIRY_DAYS);
  return date.toISOString().slice(0, 10);
}

export function keyStatus(key: ApiKey): 'active' | 'revoked' | 'expired' {
  if (key.revoked_at) return 'revoked';
  if (new Date(key.expires_at).getTime() <= Date.now()) return 'expired';
  return 'active';
}
