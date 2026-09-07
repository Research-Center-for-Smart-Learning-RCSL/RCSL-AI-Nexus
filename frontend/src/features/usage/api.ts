import { api } from '@/lib/api-client';
import {
  usageAnalyticsSchema,
  usageRecordPageSchema,
  type UsageAnalytics,
  type UsageRange,
  type UsageRecordFilters,
  type UsageRecordPage,
} from '@/features/usage/schema';

export async function getUsage(range: UsageRange): Promise<UsageAnalytics> {
  return usageAnalyticsSchema.parse(await api.get<unknown>('/usage', { query: { range } }));
}

/**
 * The caller's own usage, behind `usage:read_own`.
 *
 * Same shape, so every chart already written renders it unchanged. The path
 * carries no identity: the server reads it from the session, which is why this
 * takes no user argument and could not be pointed at anyone else.
 */
export async function getOwnUsage(range: UsageRange): Promise<UsageAnalytics> {
  return usageAnalyticsSchema.parse(await api.get<unknown>('/usage/me', { query: { range } }));
}

/**
 * One page of individual requests.
 *
 * One endpoint rather than the `/usage` and `/usage/me` pair above, and the
 * asymmetry is deliberate on the server's side: a chart is a claim about a
 * population so who it counts belongs in its name, while a row is the same
 * object whoever reads it. A reader without `usage:read_all` gets their own
 * rows from this same path, and `scoped_to_self` on the response says so.
 */
export async function listUsageRecords(filters: UsageRecordFilters): Promise<UsageRecordPage> {
  return usageRecordPageSchema.parse(
    await api.get<unknown>('/usage/records', {
      query: {
        capability: filters.capability || undefined,
        // `?? undefined` rather than `|| undefined`: `false` is a filter here
        // ("show me what was *not* compacted") and a truth test would drop it.
        compacted: filters.compacted ?? undefined,
        limit: filters.limit,
        offset: filters.offset,
      },
    }),
  );
}
