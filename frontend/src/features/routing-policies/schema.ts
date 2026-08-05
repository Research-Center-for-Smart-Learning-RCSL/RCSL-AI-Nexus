import { z } from 'zod';

import { capabilitySchema, modelStateSchema } from '@/features/models/schema';

/**
 * Mirrors the backend's `RoutingCandidateBody` / `RoutingPolicyResponse`
 * (admin_schemas.py) and ARCHITECTURE.md section 2.4. A requirement is a closed
 * set of structured fields, never an expression string: policies are authored
 * here and evaluated inside the gateway process, so an expression would turn
 * editing a policy into running code in the gateway.
 *
 * Responses are parsed against these enums rather than accepted as free
 * strings, so a status the frontend does not know surfaces as a parse failure
 * rather than a candidate that silently never matches.
 */

export const nodeStatusSchema = z.enum(['online', 'offline', 'degraded']);
export type NodeStatus = z.infer<typeof nodeStatusSchema>;

export const requirementSchema = z.object({
  node_status: z.array(nodeStatusSchema),
  model_state: z.array(modelStateSchema),
  min_free_memory_gb: z.number().nullable(),
});

export const routingCandidateSchema = z.object({
  model_alias: z.string(),
  priority: z.number().int(),
  require: requirementSchema,
});
export type RoutingCandidate = z.infer<typeof routingCandidateSchema>;

/**
 * Three states, not two. `null` is "this policy expresses no preference, take
 * the deployment default", which is what every policy written before the
 * column existed means, so the form has to be able to say it as well as `true`
 * and `false`.
 */
export const thinkingSchema = z.boolean().nullable();

export const routingPolicySchema = z.object({
  capability: capabilitySchema,
  candidates: z.array(routingCandidateSchema),
  thinking: thinkingSchema.default(null),
});
export type RoutingPolicy = z.infer<typeof routingPolicySchema>;

export const routingPolicyListSchema = z.array(routingPolicySchema);

/**
 * An optional positive number backed by a text/number input. The form holds a
 * string; an empty one means "no floor" and becomes null, anything else is
 * coerced and must be positive. Kept out of `z.coerce.number()` directly
 * because coercing `''` yields `0`, which would read as a real 0 GB floor.
 */
const optionalMemoryFloor = z.preprocess(
  (value) => (value === '' || value === null || value === undefined ? null : value),
  z.coerce.number().positive('Must be greater than zero.').nullable(),
);

const candidateFormSchema = z.object({
  model_alias: z.string().min(1, 'Choose a model alias.').max(128),
  // Number inputs hand back strings; higher priority is tried first
  // (routing_service.py sorts by descending priority).
  priority: z.coerce.number().int('Whole numbers only.'),
  require: z.object({
    node_status: z.array(nodeStatusSchema),
    model_state: z.array(modelStateSchema),
    min_free_memory_gb: optionalMemoryFloor,
  }),
});

/**
 * A three-valued control backed by a `<select>`, which can only hold strings.
 * `'default'` is the absence of a preference and becomes null on the wire;
 * the backend treats null and an omitted field identically.
 */
const thinkingFormSchema = z.preprocess(
  (value) => (value === 'default' || value === '' || value === undefined ? null : value),
  z.union([z.literal('on'), z.literal('off')]).nullable(),
);

export const savePolicyFormSchema = z.object({
  capability: capabilitySchema,
  candidates: z.array(candidateFormSchema).min(1, 'Add at least one candidate.'),
  thinking: thinkingFormSchema,
});
// `z.coerce`/`z.preprocess` above mean the form holds strings that only become
// numbers after parsing, so input and output types genuinely differ. Collapsing
// them to `z.infer` would claim the form already holds parsed values and break
// the resolver (the same reason the models form keeps both).
export type SavePolicyInput = z.input<typeof savePolicyFormSchema>;
export type SavePolicyValues = z.output<typeof savePolicyFormSchema>;

/** The request body: the capability travels in the URL, not the payload. */
export type SavePolicyRequest = {
  candidates: SavePolicyValues['candidates'];
  thinking: boolean | null;
};

/** What the `<select>` holds. `'default'` survives only until zod parses it. */
export type ThinkingChoice = 'default' | 'on' | 'off';

/**
 * The form's three-valued string, as the boolean-or-null the API takes.
 *
 * Total over the pre-parse value as well as the post-parse one, so it cannot
 * depend on having been called on the right side of the resolver. Narrowed to
 * the parsed type it read `'default'` as "not on", which is `false` — silently
 * taking a policy off the deployment default the first time it was edited.
 */
export function thinkingToApi(value: ThinkingChoice | null): boolean | null {
  if (value === 'on') return true;
  if (value === 'off') return false;
  return null;
}

/** The inverse, for loading an existing policy into the form. */
export function thinkingToForm(value: boolean | null): ThinkingChoice {
  if (value === null) return 'default';
  return value ? 'on' : 'off';
}

export const MODEL_STATES = modelStateSchema.options;
export const NODE_STATUSES = nodeStatusSchema.options;
