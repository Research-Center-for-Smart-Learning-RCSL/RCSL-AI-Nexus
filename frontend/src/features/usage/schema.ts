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

export const usageAnalyticsSchema = z.object({
  bucket: z.enum(['hour', 'day']),
  since: z.string(),
  until: z.string(),
  totals: z.array(usagePointSchema),
  by_capability: z.array(capabilitySeriesSchema),
});

export type UsageAnalytics = z.infer<typeof usageAnalyticsSchema>;
export type UsagePoint = z.infer<typeof usagePointSchema>;
