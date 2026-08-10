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

/**
 * Every action name the backend writes, for the filter's suggestion list.
 *
 * The filter is `AuditLogRow.action == action` — an exact match, not a search.
 * Presented as a bare text box it looked like one, so typing `user` returned
 * nothing and the empty state said "adjust the filters to widen the search",
 * which is advice that cannot work: there is no value between `user` and
 * `user.invited` that matches anything.
 *
 * A `datalist` rather than a `select`, so a name the backend gained after this
 * bundle was built is still typeable rather than unreachable.
 *
 * **Generated, since the hand-kept version drifted by eight names** before
 * 2026-08-08. Re-exported from here rather than imported directly by the table,
 * so the screen keeps taking its vocabulary from one module whether or not a
 * given part of it is generated.
 */
export { AUDIT_ACTIONS, type KnownAuditAction } from '@/lib/generated/audit-actions';
