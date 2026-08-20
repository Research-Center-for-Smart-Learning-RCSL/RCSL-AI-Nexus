import { z } from 'zod';

import { issuableCapabilitySchema } from '@/features/models/schema';

export const apiKeySchema = z.object({
  key_id: z.string(),
  name: z.string(),
  scopes: z.array(issuableCapabilitySchema),
  rate_limit_rpm: z.number().int().nonnegative(),
  quota_tokens_per_day: z.number().int().nonnegative(),
  allowed_cidrs: z.array(z.string()),
  expires_at: z.string(),
  owner_id: z.string(),
  owner_display: z.string().nullable(),
  revoked_at: z.string().nullable(),
  created_at: z.string().nullable(),
  last_used_at: z.string().nullable(),
  default_capability: z.string().nullable(),
  debug_logging_until: z.string().nullable(),
});
export type ApiKey = z.infer<typeof apiKeySchema>;
export const apiKeyListSchema = z.array(apiKeySchema);

export const issuedApiKeySchema = z.object({
  key: apiKeySchema,
  plaintext: z.string(),
});
export type IssuedApiKey = z.infer<typeof issuedApiKeySchema>;
