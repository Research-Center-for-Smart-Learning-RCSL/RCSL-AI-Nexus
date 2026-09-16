import { z } from 'zod';

const dashboardTrendPointSchema = z.object({
  t: z.string(),
  models_loaded: z.number().int().nonnegative(),
  models_total: z.number().int().nonnegative(),
  nodes_online: z.number().int().nonnegative(),
  nodes_total: z.number().int().nonnegative(),
  api_keys_active: z.number().int().nonnegative(),
  users_total: z.number().int().nonnegative(),
});
export type DashboardTrendPoint = z.infer<typeof dashboardTrendPointSchema>;

export const dashboardSummarySchema = z.object({
  models_total: z.number().int().nonnegative(),
  models_loaded: z.number().int().nonnegative(),
  nodes_online: z.number().int().nonnegative(),
  nodes_total: z.number().int().nonnegative(),
  api_keys_active: z.number().int().nonnegative(),
  users_total: z.number().int().nonnegative(),
  requests_last_24h: z.number().int().nonnegative().nullable(),
  tokens_last_24h: z.number().int().nonnegative().nullable(),
  trends: z.array(dashboardTrendPointSchema).default([]),
});
export type DashboardSummary = z.infer<typeof dashboardSummarySchema>;
