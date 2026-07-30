import { z } from 'zod';

/**
 * Deliberately shallow: counts the registry can answer cheaply, plus two
 * 24-hour totals from `usage_records`. The real series behind the dashboard's
 * charts live in `features/usage`; this shape stays small so the landing page
 * is one cheap query, not an analytics call.
 */

export const dashboardSummarySchema = z.object({
  models_total: z.number().int().nonnegative(),
  models_loaded: z.number().int().nonnegative(),
  nodes_online: z.number().int().nonnegative(),
  nodes_total: z.number().int().nonnegative(),
  api_keys_active: z.number().int().nonnegative(),
  users_total: z.number().int().nonnegative(),
  /** Null on a deployment that has never served a request. */
  requests_last_24h: z.number().int().nonnegative().nullable(),
  tokens_last_24h: z.number().int().nonnegative().nullable(),
});
export type DashboardSummary = z.infer<typeof dashboardSummarySchema>;
