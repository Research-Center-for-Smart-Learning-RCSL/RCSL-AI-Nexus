import { z } from 'zod';

/**
 * The audit log, from `/admin/logs`. Read-only and admin-only. Parsed rather
 * than cast, like every other response (frontend.md section 4).
 */

export const auditEntrySchema = z.object({
  id: z.string(),
  actor_id: z.string(),
  actor_display: z.string(),
  actor_source: z.string(),
  action: z.string(),
  target: z.string().nullable(),
  outcome: z.string(),
  detail: z.record(z.string(), z.string()),
  at: z.string(),
});

export const auditLogSchema = z.object({
  entries: z.array(auditEntrySchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
});

export type AuditEntry = z.infer<typeof auditEntrySchema>;
export type AuditLogPage = z.infer<typeof auditLogSchema>;

export type LogFilters = {
  action?: string;
  outcome?: string;
  limit: number;
  offset: number;
};
