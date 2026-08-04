import { api } from '@/lib/api-client';
import {
  purgeOutcomeSchema,
  retentionPolicyListSchema,
  retentionPolicySchema,
  retentionPreviewSchema,
  type PurgeOutcome,
  type RetentionDataset,
  type RetentionPolicy,
  type RetentionPreview,
} from '@/features/retention/schema';

const BASE = '/retention';

export async function listRetentionPolicies(): Promise<RetentionPolicy[]> {
  return retentionPolicyListSchema.parse(await api.get<unknown>(BASE));
}

/**
 * What a purge would remove, without removing it. `days` asks about a window
 * that has not been saved, which is what lets the form answer before the
 * decision rather than after it.
 */
export async function previewPurge(
  dataset: RetentionDataset,
  days?: number,
): Promise<RetentionPreview> {
  return retentionPreviewSchema.parse(
    await api.get<unknown>(`${BASE}/${dataset}/preview`, {
      query: days === undefined ? undefined : { days: String(days) },
    }),
  );
}

export async function setRetentionPolicy(
  dataset: RetentionDataset,
  days: number,
): Promise<RetentionPolicy> {
  return retentionPolicySchema.parse(await api.put<unknown>(`${BASE}/${dataset}`, { days }));
}

/** `days` narrows this one run without changing the standing policy. */
export async function purgeDataset(
  dataset: RetentionDataset,
  days?: number,
): Promise<PurgeOutcome> {
  return purgeOutcomeSchema.parse(
    await api.post<unknown>(`${BASE}/${dataset}/purge`, undefined, {
      query: days === undefined ? undefined : { days: String(days) },
    }),
  );
}
