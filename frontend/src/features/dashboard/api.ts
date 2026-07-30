import { api } from '@/lib/api-client';
import {
  dashboardSummarySchema,
  type DashboardSummary,
} from '@/features/dashboard/schema';

/**
 * One snapshot per visit: counts plus two 24-hour totals. The charts on the
 * dashboard read `/admin/usage` through `features/usage`, not this endpoint,
 * and nothing here polls — the numbers move slowly enough that a refresh is
 * the user reloading the page.
 */
export async function getDashboardSummary(): Promise<DashboardSummary> {
  return dashboardSummarySchema.parse(await api.get<unknown>('/dashboard'));
}
