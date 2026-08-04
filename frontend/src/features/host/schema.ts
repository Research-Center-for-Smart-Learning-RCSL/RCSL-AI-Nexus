import { z } from 'zod';

/**
 * The Mac's own free memory and disk, from `/admin/host`.
 *
 * Every field is nullable and `reporting` is separate, because "the agent did
 * not answer" and "there is none left" are opposite states that would otherwise
 * both render as zero. The launchd agent is optional infrastructure; a
 * deployment without it is not broken.
 */

const nullableNumber = z.number().nullable();

export const hostStatusSchema = z.object({
  reporting: z.boolean(),
  memory: z.object({
    total_gb: nullableNumber,
    available_gb: nullableNumber,
    swap_used_gb: nullableNumber,
  }),
  disk: z.object({
    volume: z.string().nullable(),
    total_gb: nullableNumber,
    free_gb: nullableNumber,
  }),
  system: z.object({
    load_1m: nullableNumber,
    load_5m: nullableNumber,
    load_15m: nullableNumber,
    cpu_count: z.number().int().nullable(),
    uptime_seconds: z.number().int().nullable(),
  }),
});

export type HostStatus = z.infer<typeof hostStatusSchema>;

/** Days and hours. Seconds since boot is a number nobody reads as a duration. */
export function formatUptime(seconds: number | null): string {
  if (seconds === null) return '—';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  if (days > 0) return `${days}d ${hours}h`;
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}
