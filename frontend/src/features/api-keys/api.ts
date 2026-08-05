import { api } from '@/lib/api-client';
import {
  apiKeyListSchema,
  apiKeySchema,
  issuedApiKeySchema,
  type ApiKey,
  type CreateApiKeyPayload,
  type IssuedApiKey,
  type UpdateApiKeyPayload,
} from '@/features/api-keys/schema';

const BASE = '/api-keys';

export async function listApiKeys(): Promise<ApiKey[]> {
  return apiKeyListSchema.parse(await api.get<unknown>(BASE));
}

/** The plaintext in this response is the only copy that will ever exist. */
export async function issueApiKey(
  input: CreateApiKeyPayload,
): Promise<IssuedApiKey> {
  return issuedApiKeySchema.parse(await api.post<unknown>(BASE, input));
}

/**
 * A PATCH: every field is optional server-side, so an omitted one is left
 * alone rather than cleared. The edit dialog sends all of them, but the
 * signature keeps the endpoint's contract rather than the dialog's habit.
 */
export async function updateApiKey(
  keyId: string,
  input: Partial<UpdateApiKeyPayload>,
): Promise<ApiKey> {
  return apiKeySchema.parse(await api.patch<unknown>(`${BASE}/${keyId}`, input));
}

/**
 * Takes effect immediately, because the gateway re-reads the row on every
 * request. There is no verification cache to drop: security.md §4.2 records
 * the 60-second Redis cache an early draft described as a deliberate
 * non-feature, since it would reintroduce a revocation window.
 */
export async function revokeApiKey(keyId: string): Promise<void> {
  await api.post<void>(`${BASE}/${keyId}/revoke`);
}

/**
 * Open (minutes > 0) or close (0) the key's debug window: while it is open,
 * error responses to this key carry the operator-facing detail that is
 * otherwise log-only. Time-boxed by the backend to at most 24 hours, and
 * audited, because it loosens an information control.
 */
export async function setDebugWindow(
  keyId: string,
  minutes: number,
): Promise<ApiKey> {
  return apiKeySchema.parse(
    await api.post<unknown>(`${BASE}/${keyId}/debug`, { minutes }),
  );
}
