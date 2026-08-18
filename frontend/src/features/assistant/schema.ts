import { z } from 'zod';

import { issuableCapabilitySchema } from '@/features/models/schema';
// The select's sentinel for "refuse". This module already names form fields
// (`allowed_cidrs_text`) and already carries the key draft, so the direction of
// this import matches the coupling that was already here.
import { NO_DEFAULT } from '@/features/api-keys/schema';

/**
 * The management assistant's wire contract, mirroring the backend's
 * `interfaces/http/schemas/assistant_schemas.py`.
 *
 * The role enum has two values, not three. That is the same control the backend
 * enforces, expressed on this side too: the assistant's instructions are
 * assembled from live domain values on the server, and a client able to send a
 * `system` turn could replace the rules it is meant to state. Nothing here
 * would stop a hand-written request, which is why the server is where it counts
 * — but a type that cannot express the override means no component can add one
 * by accident either.
 */
export const assistRoleSchema = z.enum(['user', 'assistant']);
export type AssistRole = z.infer<typeof assistRoleSchema>;

export const assistMessageSchema = z.object({
  role: assistRoleSchema,
  content: z.string().min(1).max(8000),
});
export type AssistMessage = z.infer<typeof assistMessageSchema>;

/** Which screen the drawer was opened from. A closed set; see the backend. */
export const assistSurfaceSchema = z.enum([
  'api_keys.list',
  'api_keys.create',
  'api_keys.edit',
  'api_docs',
  'agent_setup',
  'other',
]);
export type AssistSurface = z.infer<typeof assistSurfaceSchema>;

/**
 * What the key form currently holds, as typed.
 *
 * Every field is a string or a list of strings, including the two numeric ones,
 * because that is what the form actually holds before `z.coerce` runs. A draft
 * is published precisely when it does not yet validate — that is usually why
 * help is being asked for — so a stricter type here would drop the context in
 * exactly the case it was wanted.
 *
 * **This type is the boundary that keeps a key's plaintext out of the
 * assistant.** `IssuedApiKey` carries the one copy of a secret that will ever
 * exist, and the create dialog holds it in scope at the moment it would be
 * natural to publish "the whole form state". There is no field here it could
 * arrive in, so the omission is structural rather than a rule to remember.
 */
export const apiKeyDraftSchema = z.object({
  name: z.string().max(200).optional(),
  scopes: z.array(issuableCapabilitySchema).max(20).optional(),
  rate_limit_rpm: z.string().max(40).optional(),
  quota_tokens_per_day: z.string().max(40).optional(),
  allowed_cidrs: z.array(z.string()).max(40).optional(),
  expires_at: z.string().max(60).optional(),
  /** What the default-capability select holds, as a capability name — or
   *  absent, which is "refuse". The select's own sentinel does not travel; the
   *  backend declares `extra="forbid"` on this draft, so a field published
   *  here and undeclared there costs the whole draft. */
  default_capability: z.string().max(64).optional(),
});
export type ApiKeyDraft = z.infer<typeof apiKeyDraftSchema>;

export const assistRequestSchema = z.object({
  surface: assistSurfaceSchema,
  messages: z.array(assistMessageSchema).min(1).max(40),
  draft: apiKeyDraftSchema.optional(),
  key_id: z.string().max(64).optional(),
});
export type AssistRequest = z.infer<typeof assistRequestSchema>;

/**
 * The fields a proposal may fill. Mirrors the backend's `UpdateApiKeyRequest`,
 * which is what validates the model's output there — so anything that reaches
 * this schema has already been held to the bounds the API itself enforces, and
 * to the expiry window and capability list this deployment applies.
 *
 * Parsed again here rather than trusted. The frame arrives on the same
 * connection as the model's prose, and this is the last point before values
 * land in a form the operator is one click from saving. `strict()` because an
 * unexpected key means this is not the frame it claims to be: zod's default is
 * to strip unknown keys, and a schema that silently accepted anything is how
 * the chat panel once rendered every frame as an empty object.
 */
export const proposalFieldsSchema = z
  .object({
    name: z.string().min(1).max(80).optional(),
    scopes: z.array(issuableCapabilitySchema).min(1).optional(),
    rate_limit_rpm: z.number().int().min(1).max(100_000).optional(),
    quota_tokens_per_day: z.number().int().min(1).optional(),
    allowed_cidrs: z.array(z.string()).optional(),
    expires_at: z.string().optional(),
    /** Nullable, unlike every other field here, because `null` is the value
     *  that means "refuse" rather than an omission. Added the day
     *  `UpdateApiKeyRequest` gained it: `strict()` drops the entire card on an
     *  unknown key, so a field the backend will happily validate and this
     *  schema does not know costs the operator the whole proposal, including
     *  the recommendations that were fine. */
    default_capability: z.string().nullable().optional(),
  })
  .strict();
export type ProposalFields = z.infer<typeof proposalFieldsSchema>;

export const proposalSchema = z
  .object({
    action: z.enum(['create', 'update']),
    key_id: z.string().optional(),
    fields: proposalFieldsSchema,
    rationale: z.string().max(400),
  })
  .strict();
export type Proposal = z.infer<typeof proposalSchema>;

/**
 * The trailer frame, emitted after the answer and before `[DONE]`.
 *
 * Read from the raw frame rather than through `streamFrameSchema`, which
 * describes the OpenAI envelope and strips everything else. Returns null for
 * every ordinary frame, so the reader can offer it each one without the caller
 * needing to know which is which.
 */
export function readProposalFrame(raw: unknown): Proposal | null {
  if (typeof raw !== 'object' || raw === null || !('proposal' in raw)) {
    return null;
  }
  const parsed = proposalSchema.safeParse((raw as { proposal: unknown }).proposal);
  return parsed.success ? parsed.data : null;
}

/**
 * A proposal's fields as the form holds them: strings, and the CIDR list
 * flattened into the one textarea both key dialogs use.
 *
 * Returns only the keys the proposal actually named. An omitted field must
 * leave what the operator already typed alone — filling it with a default would
 * turn "here is a better expiry" into "and I also reset your rate limit", which
 * is the one behaviour that would make the card untrustworthy.
 */
export function proposalToFormPatch(
  fields: ProposalFields,
): Record<string, string | string[]> {
  const patch: Record<string, string | string[]> = {};
  if (fields.name !== undefined) patch.name = fields.name;
  if (fields.scopes !== undefined) patch.scopes = fields.scopes;
  if (fields.rate_limit_rpm !== undefined) {
    patch.rate_limit_rpm = String(fields.rate_limit_rpm);
  }
  if (fields.quota_tokens_per_day !== undefined) {
    patch.quota_tokens_per_day = String(fields.quota_tokens_per_day);
  }
  if (fields.allowed_cidrs !== undefined) {
    patch.allowed_cidrs_text = fields.allowed_cidrs.join('\n');
  }
  if (fields.default_capability !== undefined) {
    // `null` is the wire's "refuse"; the select holds a word for it, because an
    // empty string renders as the placeholder. Imported rather than repeated so
    // the two spellings cannot drift.
    patch.default_capability = fields.default_capability ?? NO_DEFAULT;
  }
  if (fields.expires_at !== undefined) {
    // The form's date input takes `YYYY-MM-DD`; the proposal carries a full
    // timestamp. An unparsable value is dropped rather than written, so the
    // field keeps whatever it had instead of going blank and failing its own
    // required rule.
    const date = new Date(fields.expires_at);
    if (!Number.isNaN(date.getTime())) {
      patch.expires_at = date.toISOString().slice(0, 10);
    }
  }
  return patch;
}
