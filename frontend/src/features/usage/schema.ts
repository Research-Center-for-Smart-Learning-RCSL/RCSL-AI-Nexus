import { z } from 'zod';

/**
 * Usage over time, from `/admin/usage`. Parsed rather than cast, so a field the
 * backend renames surfaces here on the next call rather than as `undefined` in a
 * chart (frontend.md section 4).
 */

export const USAGE_RANGES = ['24h', '7d', '30d'] as const;
export type UsageRange = (typeof USAGE_RANGES)[number];

const usagePointSchema = z.object({
  t: z.string(),
  requests: z.number().int().nonnegative(),
  tokens: z.number().int().nonnegative(),
});

const capabilitySeriesSchema = z.object({
  capability: z.string(),
  points: z.array(usagePointSchema),
});

const compactionTierCountSchema = z.object({
  tier: z.number().int().nonnegative(),
  requests: z.number().int().nonnegative(),
});

/**
 * How many of the requests in the window had their prompt reduced before it
 * reached the model, and by which tier.
 *
 * Beside the charts rather than on a screen of its own because it is only
 * meaningful as a ratio: "eleven compactions" says nothing without the request
 * count next to it, and that count is already on this response.
 */
const compactionSummarySchema = z.object({
  requests: z.number().int().nonnegative(),
  tokens_removed: z.number().int().nonnegative(),
  by_tier: z.array(compactionTierCountSchema),
});

export const usageAnalyticsSchema = z.object({
  bucket: z.enum(['hour', 'day']),
  since: z.string(),
  until: z.string(),
  totals: z.array(usagePointSchema),
  by_capability: z.array(capabilitySeriesSchema),
  compaction: compactionSummarySchema,
});

export type UsageAnalytics = z.infer<typeof usageAnalyticsSchema>;
export type UsagePoint = z.infer<typeof usagePointSchema>;
export type CompactionSummary = z.infer<typeof compactionSummarySchema>;

/**
 * One served request, from `/admin/usage/records`.
 *
 * The charts above this table are counts; these are the rows behind them. The
 * table has been written since the first migration and had no reader that
 * returned a row until 2026-09-07 — every consumer was an aggregate, so the
 * platform recorded what each request did and could show nobody any of it.
 *
 * Carries no prompt and no completion, because the row never held either. That
 * is what lets this be the general per-request surface: transcripts hold the
 * text and exist only while a debug window is open.
 */
export const usageRecordSchema = z.object({
  id: z.string(),
  at: z.string(),
  actor_id: z.string(),
  api_key_id: z.string().nullable(),
  capability: z.string(),
  requested_capability: z.string().nullable(),
  model_alias: z.string(),
  tokens: z.number().int().nonnegative(),
  prompt_tokens: z.number().int().nonnegative(),
  latency_ms: z.number().int().nonnegative(),
  completed: z.boolean(),
  compaction_tier: z.number().int().nonnegative().nullable(),
  tokens_before_compaction: z.number().int().nonnegative().nullable(),
  tokens_after_compaction: z.number().int().nonnegative().nullable(),
});

export const usageRecordPageSchema = z.object({
  entries: z.array(usageRecordSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
  /** True when the reader may see only their own requests, so the table can
   *  say so rather than showing controls that silently do nothing. */
  scoped_to_self: z.boolean(),
});

export type UsageRecord = z.infer<typeof usageRecordSchema>;
export type UsageRecordPage = z.infer<typeof usageRecordPageSchema>;

export type UsageRecordFilters = {
  capability?: string;
  compacted?: boolean;
  limit: number;
  offset: number;
};
