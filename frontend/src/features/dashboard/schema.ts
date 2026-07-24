import { z } from 'zod';

/**
 * Dashboard is Phase 1 with static data and Phase 2 with real metrics
 * (ARCHITECTURE.md section 3). Live figures come from Prometheus through
 * `MetricsPort`, which does not exist yet, so everything below is deliberately
 * shallow and the UI labels it as such.
 */

export const dashboardSummarySchema = z.object({
  models_total: z.number().int().nonnegative(),
  models_loaded: z.number().int().nonnegative(),
  nodes_online: z.number().int().nonnegative(),
  nodes_total: z.number().int().nonnegative(),
  api_keys_active: z.number().int().nonnegative(),
  users_total: z.number().int().nonnegative(),
  /** Phase 2. Null until usage analytics exists. */
  requests_last_24h: z.number().int().nonnegative().nullable(),
  tokens_last_24h: z.number().int().nonnegative().nullable(),
});
export type DashboardSummary = z.infer<typeof dashboardSummarySchema>;
