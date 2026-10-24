import { z } from 'zod';

import { api } from '@/lib/api-client';

/** What a platform administrator sees of the hold (#61). */
export const maintenanceAdminSchema = z.object({
  closed: z.boolean(),
  phase: z.string(),
  epoch: z.number(),
  revision: z.number(),
  message: z.string().nullable(),
  expected_return_at: z.string().nullable(),
  changed_by: z.string().nullable(),
  changed_at: z.string().nullable(),
  enabled: z.boolean(),
});
export type MaintenanceAdmin = z.infer<typeof maintenanceAdminSchema>;

export type MaintenanceNotice = {
  message: string | null;
  expected_return_at: string | null;
};

const BASE = '/maintenance';

export async function getMaintenance(): Promise<MaintenanceAdmin> {
  return maintenanceAdminSchema.parse(await api.get<unknown>(BASE));
}

export async function enterMaintenance(notice: MaintenanceNotice): Promise<MaintenanceAdmin> {
  return maintenanceAdminSchema.parse(await api.post<unknown>(`${BASE}/enter`, notice));
}

export async function reopenAfterMaintenance(): Promise<MaintenanceAdmin> {
  return maintenanceAdminSchema.parse(await api.post<unknown>(`${BASE}/reopen`));
}

export async function setMaintenanceMessage(
  notice: MaintenanceNotice & { expected_revision: number },
): Promise<MaintenanceAdmin> {
  return maintenanceAdminSchema.parse(await api.put<unknown>(`${BASE}/message`, notice));
}
