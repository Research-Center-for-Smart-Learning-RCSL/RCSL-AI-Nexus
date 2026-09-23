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

const hostMemorySchema = z.object({
  total_gb: z.number(),
  available_gb: z.number(),
});

const latencyStatsSchema = z.object({
  count: z.number().int().nonnegative(),
  avg_ms: z.number().int().nonnegative(),
  p50_ms: z.number().int().nonnegative(),
  p95_ms: z.number().int().nonnegative(),
});

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
  host_memory: hostMemorySchema.nullable().default(null),
  latency: latencyStatsSchema.nullable().default(null),
});
export type DashboardSummary = z.infer<typeof dashboardSummarySchema>;
