import { z } from 'zod';

import { api } from '@/lib/api-client';

const snapshotModelSchema = z
  .object({
    name: z.string().optional(),
    digest: z.string().optional(),
    size: z.number().optional(),
    context_length: z.number().nullable().optional(),
  })
  .passthrough();
export type SnapshotModel = z.infer<typeof snapshotModelSchema>;

/** One node's progress through an entry or a restore (#61 P4, P5). */
const nodeStepSchema = z.object({
  node_id: z.string(),
  phase: z.string(),
  status: z.string(),
  attempts: z.number(),
  error: z.string().nullable(),
  snapshot: z.array(snapshotModelSchema).nullable(),
  snapshot_at: z.string().nullable(),
  snapshot_error: z.string().nullable(),
  interrupted: z.array(z.string()),
  accounting: z.string().nullable(),
});
export type MaintenanceNodeStep = z.infer<typeof nodeStepSchema>;

const operationSchema = z.object({
  id: z.string(),
  kind: z.string(),
  epoch: z.number(),
  status: z.string(),
  requested_by: z.string(),
  error: z.string().nullable(),
  created_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  nodes: z.array(nodeStepSchema),
});
export type MaintenanceOperation = z.infer<typeof operationSchema>;

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
  operation: operationSchema.nullable().optional(),
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

export async function restoreAfterMaintenance(): Promise<MaintenanceAdmin> {
  return maintenanceAdminSchema.parse(await api.post<unknown>(`${BASE}/restore`));
}

export async function retryMaintenance(): Promise<MaintenanceAdmin> {
  return maintenanceAdminSchema.parse(await api.post<unknown>(`${BASE}/retry`));
}
