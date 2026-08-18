import { z } from 'zod';

/**
 * Refusals, from `/admin/refusals`. Why the platform said no, in the words it
 * said it in.
 *
 * **Every row here is a second copy of a response its subject already
 * received.** The code they branched on, the status, the message they read, and
 * the caller-facing figures that came with it — built by the same function that
 * builds the response body, so the two cannot disagree. Nothing operator-facing
 * is in it: `detail` never leaves the backend process, and the model's alias is
 * withheld from a refusal exactly as it is from the response the refusal was.
 *
 * That is why this screen is not admin-only. Reading your own is in the base
 * scopes; reading everybody's is `refusal:read_all`, and the response says
 * which of the two you got rather than showing a filter that silently does
 * nothing.
 */

export const refusalSchema = z.object({
  id: z.string(),
  at: z.string(),
  code: z.string(),
  status: z.number().int(),
  actor_id: z.string(),
  /**
   * The login, or the key handle for a gateway caller. Denormalised onto the
   * row rather than joined, so it survives the account being deleted — which
   * is when somebody is most likely to be asking whose these were. Empty on a
   * row written before the column existed.
   */
  actor_display: z.string(),
  api_key_id: z.string().nullable(),
  surface: z.string(),
  method: z.string(),
  path: z.string(),
  request_id: z.string().nullable(),
  message: z.string(),
  /**
   * The figures, keyed by name and left unmodelled on purpose.
   *
   * The set differs per code — `estimated`/`limit`/`composition`/`basis` on a
   * `context_too_long`, `retry_after_seconds` on the three that carry a wait,
   * `maximum_days` on an API key's expiry — and it is the part most likely to
   * grow: nine error classes carry one today and four more are specified to.
   * A shape declared here would be a third place for that set to drift, and a
   * new figure would arrive as a field this screen silently dropped.
   */
  figures: z.record(z.string(), z.unknown()),
});

export const refusalPageSchema = z.object({
  entries: z.array(refusalSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
  scoped_to_self: z.boolean(),
});

export type Refusal = z.infer<typeof refusalSchema>;
export type RefusalPage = z.infer<typeof refusalPageSchema>;

export type RefusalFilters = {
  code?: string;
  request_id?: string;
  /**
   * Only ever set by a reader holding `refusal:read_all`. The server narrows
   * anyone else to themselves whatever this says, so it is a convenience here
   * and not a control.
   */
  actor_id?: string;
  /**
   * A substring of the name recorded on the row, matched case-insensitively.
   *
   * The sibling of `actor_id` rather than a replacement for it, because the
   * two find different things. An id is exact and follows the account: it
   * catches a person's gateway refusals, whose recorded display is the *key's*
   * handle and not their login. A name is the only thing that still finds the
   * refusals of an account that has since been deleted, which is when somebody
   * is most likely to be asking whose these were.
   *
   * `accountQuery` in `./account` picks between them. Like `actor_id`, it is
   * ANDed with the server's own narrowing, so it can only subtract from what
   * the reader was already allowed to see.
   */
  actor_display?: string;
  /**
   * The window, as ISO instants. Half-open — `since` is inclusive and `until`
   * is exclusive — which is the backend's comparison and not a detail worth
   * hiding: the controls are labelled "From" and "Before" so the boundary
   * reads the way it behaves.
   */
  since?: string;
  until?: string;
  limit: number;
  offset: number;
};

/**
 * The remedy a caller can act on, chosen by code rather than by status.
 *
 * Status is too coarse and it is the reason this table exists: the evening of
 * 2026-08-17 had two 413s with different causes and two 409s with nothing in
 * common, and both pairs read as the same failure to the people receiving them.
 *
 * Returning `null` rather than a generic sentence is deliberate. A message that
 * says "try again or contact an administrator" on a refusal nobody has thought
 * about is worse than saying nothing: it implies the platform knows what to do
 * about it, and the row already carries the sentence the caller was actually
 * given.
 */
export function remedyFor(code: string): string | null {
  switch (code) {
    case 'context_too_long':
      return 'Read the composition before choosing a fix. A conversation that grew is fixed by starting a new one; one enormous message by not reading that file in; tool definitions that dominate by trimming the client’s tool list — for which a new conversation does nothing, since they are resent every turn.';
    case 'request_too_large':
      return 'The body itself was over the byte ceiling, before any of it was read as tokens. Sending fewer or smaller attachments is the only thing that changes it.';
    case 'capability_not_issued':
      return 'The `model` field on this platform takes a capability, not a model name. `available` lists what this key may call.';
    case 'api_key_lifetime':
      return 'The expiry typed was beyond the maximum a key may last. `maximum_days` is that maximum, counted from today.';
    case 'quota_exceeded':
      return 'The daily allowance is spent. It recovers in pieces rather than resetting, so `retry_after_seconds` is when the first of it comes back.';
    case 'rate_limited':
      return 'Too many requests too quickly. `retry_after_seconds` is the wait that was asked for.';
    case 'insufficient_memory':
      return 'The node could not fit this model beside what it already holds. Unloading another model is the operator’s move here, not the caller’s.';
    case 'no_available_model':
      return 'Nothing was serving that capability at the time. This one is an administrator’s to fix, and retrying alone does not.';
    default:
      return null;
  }
}

/** Figures worth showing as a labelled pair rather than as raw JSON. */
export const FIGURE_LABELS: Record<string, string> = {
  estimated: 'counted',
  limit: 'limit',
  basis: 'counted by',
  composition: 'where it went',
  retry_after_seconds: 'wait asked for',
  maximum_days: 'maximum days',
  required_gb: 'needed (GB)',
  available_gb: 'free (GB)',
  capability: 'capability',
  available: 'available',
  reason: 'reason',
};
