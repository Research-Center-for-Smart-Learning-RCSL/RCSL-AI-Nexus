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

export const routingPolicySchema = z.object({
  capability: capabilitySchema,
  candidates: z.array(routingCandidateSchema),
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

export const savePolicyFormSchema = z.object({
  capability: capabilitySchema,
  candidates: z.array(candidateFormSchema).min(1, 'Add at least one candidate.'),
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
};

export const MODEL_STATES = modelStateSchema.options;
export const NODE_STATUSES = nodeStatusSchema.options;
