import { api } from '@/lib/api-client';
import {
  apiKeyListSchema,
  apiKeySchema,
  issuedApiKeySchema,
  type ApiKey,
  type CreateApiKeyInput,
  type IssuedApiKey,
} from '@/features/api-keys/schema';

const BASE = '/api-keys';

export async function listApiKeys(): Promise<ApiKey[]> {
  return apiKeyListSchema.parse(await api.get<unknown>(BASE));
}

/** The plaintext in this response is the only copy that will ever exist. */
export async function issueApiKey(
  input: CreateApiKeyInput,
): Promise<IssuedApiKey> {
  return issuedApiKeySchema.parse(await api.post<unknown>(BASE, input));
}

export async function updateApiKey(
  keyId: string,
  input: Partial<CreateApiKeyInput>,
): Promise<ApiKey> {
  return apiKeySchema.parse(await api.patch<unknown>(`${BASE}/${keyId}`, input));
}

/** Takes effect immediately; the backend drops the Redis verification cache. */
export async function revokeApiKey(keyId: string): Promise<void> {
  await api.post<void>(`${BASE}/${keyId}/revoke`);
}
