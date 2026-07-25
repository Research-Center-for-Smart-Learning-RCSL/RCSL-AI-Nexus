import { z } from 'zod';

import { runtimeKindSchema } from '@/features/models/schema';

/**
 * The node read schema stays in `features/models` next to `runtimeKindSchema`,
 * so re-export it here rather than redefine it (a second definition importing
 * that enum would be a circular import). This feature adds the write side that
 * Phase 2 introduced, shipping with the SSRF guard (security.md section 7.2).
 */
export {
  nodeSchema,
  nodeListSchema,
  type Node,
  RUNTIME_LABELS,
} from '@/features/models/schema';

export const nodeStatusSchema = z.enum(['online', 'offline', 'degraded']);
export type NodeStatus = z.infer<typeof nodeStatusSchema>;

export const NODE_STATUS_HINT: Record<NodeStatus, string> = {
  online: 'Every declared runtime answered its health check.',
  degraded: 'Some declared runtimes answered and some did not.',
  offline: 'No declared runtime answered, or none could be probed.',
};

export const createNodeSchema = z.object({
  name: z.string().min(1, 'Required').max(128),
  // The authoritative check is the egress guard server-side, which resolves the
  // address and requires it inside the tailnet range. This bound only stops an
  // absurd value; the real rule lives in the use case.
  address: z.string().min(1, 'Required').max(255),
  // Coerced because number inputs hand back strings.
  total_memory_gb: z.coerce.number().positive(),
  runtimes: z
    .array(runtimeKindSchema)
    .min(1, 'Choose at least one runtime.'),
});
// As in the model form, the input holds strings and the output holds parsed
// numbers, so the two types are genuinely different.
export type CreateNodeInput = z.input<typeof createNodeSchema>;
export type CreateNodeValues = z.output<typeof createNodeSchema>;

export const updateNodeSchema = createNodeSchema.partial();
export type UpdateNodeInput = z.input<typeof updateNodeSchema>;
