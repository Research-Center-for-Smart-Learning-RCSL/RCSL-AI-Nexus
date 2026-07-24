import { api } from '@/lib/api-client';
import {
  dashboardSummarySchema,
  type DashboardSummary,
} from '@/features/dashboard/schema';

/**
 * `/admin/dashboard` exists in Phase 1 but serves static counts. Charts and
 * live metrics are Phase 2, so nothing here polls.
 */
export async function getDashboardSummary(): Promise<DashboardSummary> {
  return dashboardSummarySchema.parse(await api.get<unknown>('/dashboard'));
}
