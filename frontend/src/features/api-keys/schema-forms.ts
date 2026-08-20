import { z } from 'zod';

import {
  issuableCapabilitySchema,
  type IssuableCapability,
} from '@/features/models/schema';

import { cidrTextSchema } from './schema-cidr';
import { defaultWithinScopes, NO_DEFAULT } from './schema-default-capability';

const sharedFields = {
  name: z.string().min(1, 'Required').max(80),
  scopes: z
    .array(issuableCapabilitySchema)
    .min(1, 'Choose at least one capability.'),
  rate_limit_rpm: z.coerce.number().int().positive(),
  quota_tokens_per_day: z.coerce.number().int().positive(),
  allowed_cidrs_text: cidrTextSchema,
  expires_at: z.string().min(1, 'An expiry is required.'),
  default_capability: z.string().default(NO_DEFAULT),
};

export const createApiKeySchema = z
  .object({ ...sharedFields, owner_id: z.string().min(1, 'Required') })
  .superRefine(defaultWithinScopes);
export type CreateApiKeyInput = z.input<typeof createApiKeySchema>;
export type CreateApiKeyValues = z.output<typeof createApiKeySchema>;
export type CreateApiKeyPayload = {
  name: string;
  owner_id: string;
  scopes: IssuableCapability[];
  rate_limit_rpm: number;
  quota_tokens_per_day: number;
  allowed_cidrs: string[];
  expires_at: string;
  default_capability: string | null;
};

export const updateApiKeySchema = z
  .object(sharedFields)
  .superRefine(defaultWithinScopes);
export type UpdateApiKeyInput = z.input<typeof updateApiKeySchema>;
export type UpdateApiKeyValues = z.output<typeof updateApiKeySchema>;
export type UpdateApiKeyPayload = {
  name: string;
  scopes: IssuableCapability[];
  rate_limit_rpm: number;
  quota_tokens_per_day: number;
  allowed_cidrs: string[];
  expires_at: string;
  default_capability: string | null;
};
