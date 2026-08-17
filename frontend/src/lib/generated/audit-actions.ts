/**
 * Generated from the backend audit action catalogue. Do not edit.
 *
 *     scripts/generate-api-types.sh
 *
 * Every action name the platform writes to the audit log, taken from
 * `domain/entities/audit.py`. `AuditPort.record` takes that enum, so an action
 * a use case can write is necessarily one of these.
 *
 * This file exists because the hand-kept version of it drifted by eight names
 * before 2026-08-08, and each missing name was an action the `/admin/logs`
 * filter could not offer -- the filter matches exactly, so a name absent here
 * is unreachable to anyone who does not already know how it is spelled. A
 * generated copy cannot drift: CI regenerates it and fails if the committed
 * result differs.
 */

export const AUDIT_ACTIONS = [
  'api_key.debug_window_set',
  'api_key.issued',
  'api_key.revoked',
  'api_key.updated',
  'authz.denied',
  'bootstrap.first_admin',
  'evaluation.deleted',
  'evaluation.imported',
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
  'refusal.read_any',
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

/**
 * An action name known at build time.
 *
 * Deliberately not the type of `AuditEntry.action`, which stays `string`:
 * that types what the server sends, and a log row written by a backend
 * newer than this bundle is still a row to render rather than a parse
 * failure. Use this one wherever an action is *authored*.
 */
export type KnownAuditAction = (typeof AUDIT_ACTIONS)[number];
