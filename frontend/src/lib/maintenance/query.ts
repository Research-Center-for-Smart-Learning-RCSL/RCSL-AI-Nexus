import { z } from 'zod';

import { api } from '@/lib/api-client';

/**
 * The public half of the maintenance hold (#61). Answered without signing in,
 * so it is what decides, before any identity, whether this browser sees the
 * platform or the maintenance page.
 */
export const maintenanceStatusSchema = z.object({
  closed: z.boolean(),
  phase: z.string(),
  message: z.string().nullable(),
  expected_return_at: z.string().nullable(),
  revision: z.number(),
});
export type MaintenanceStatus = z.infer<typeof maintenanceStatusSchema>;

export const MAINTENANCE_STATUS_QUERY_KEY = ['maintenance', 'status'] as const;

export async function fetchMaintenanceStatus(): Promise<MaintenanceStatus> {
  return maintenanceStatusSchema.parse(await api.get<unknown>('/maintenance/status'));
}
