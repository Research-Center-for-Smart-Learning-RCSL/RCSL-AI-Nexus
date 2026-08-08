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
 * A `datalist` rather than a `select`, so a name added to the backend after
 * this list was written is still typeable rather than unreachable. Kept
 * alphabetical to match how it renders.
 *
 * **It had drifted by eight names before 2026-08-08**, found while adding
 * `prompt_log.read`: both `debug_window_set` events, all three
 * `prompt_template.*` and both `retention.*` had shipped without being added
 * here. Every one of them is an action an operator could only filter for by
 * already knowing its exact spelling — which is the failure this list was
 * written to remove, reappearing because the list and the actions live in
 * different languages with nothing joining them.
 *
 * The durable fix is the one `/admin/roles` already uses for the role
 * catalogue: serve the set from the table that writes it, so the screen
 * explaining a thing is generated from the thing. Recorded in PROGRESS
 * 2026-08-08 rather than done here, because it is a different change from the
 * one this list was touched for.
 */
export const AUDIT_ACTIONS = [
  'api_key.debug_window_set',
  'api_key.issued',
  'api_key.revoked',
  'api_key.updated',
  'authz.denied',
  'bootstrap.first_admin',
  'knowledge.collection_created',
  'knowledge.collection_deleted',
  'knowledge.document_deleted',
  'knowledge.document_uploaded',
  'model.deleted',
  'model.download_started',
  'model.loaded',
  'model.registered',
  'model.unloaded',
  'model.updated',
  'node.registered',
  'node.removed',
  'node.updated',
  'prompt_log.read',
  'prompt_template.created',
  'prompt_template.deleted',
  'prompt_template.updated',
  'retention.policy_set',
  'retention.purged',
  'routing_policy.deleted',
  'routing_policy.saved',
  'tenant.created',
  'user.debug_window_set',
  'user.deleted',
  'user.disabled',
  'user.enabled',
  'user.invitation_accepted',
  'user.invitation_reissued',
  'user.invited',
  'user.password_changed',
  'user.password_reset_consumed',
  'user.password_reset_issued',
  'user.password_verified',
  'user.recovery_code_used',
  'user.role_changed',
  'user.sign_in_failed',
  'user.sign_in_throttled',
  'user.signed_in',
  'user.signed_out',
  'user.totp_enrolled',
  'user.totp_reenrolled',
  'user.updated',
] as const;
