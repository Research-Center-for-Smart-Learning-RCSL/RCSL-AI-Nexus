import { api } from '@/lib/api-client';
import {
  usageAnalyticsSchema,
  type UsageAnalytics,
  type UsageRange,
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
