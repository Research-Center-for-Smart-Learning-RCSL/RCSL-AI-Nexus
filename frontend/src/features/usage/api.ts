import { api } from '@/lib/api-client';
import {
  usageAnalyticsSchema,
  type UsageAnalytics,
  type UsageRange,
} from '@/features/usage/schema';

export async function getUsage(range: UsageRange): Promise<UsageAnalytics> {
  return usageAnalyticsSchema.parse(await api.get<unknown>('/usage', { query: { range } }));
}
