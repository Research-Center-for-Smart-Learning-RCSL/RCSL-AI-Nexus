import { z } from 'zod';

/**
 * Mirrors ARCHITECTURE.md section 2.2. Defined once and used for both
 * `zodResolver` validation and `z.infer` types (frontend.md section 5).
 *
 * These shapes will be checked against `src/lib/generated/admin-api.ts` once
 * `pnpm sync-types` has run against a live admin API; the zod schemas stay
 * because generated types validate nothing at runtime.
 */

export const runtimeKindSchema = z.enum(['ollama', 'mlx', 'vllm', 'llamacpp']);
export type RuntimeKind = z.infer<typeof runtimeKindSchema>;

export const modelStateSchema = z.enum([
  'not_downloaded',
  'downloading',
  'downloaded',
  'loading',
  'loaded',
  'unloading',
  'error',
]);
export type ModelState = z.infer<typeof modelStateSchema>;

export const capabilitySchema = z.enum([
  'chat',
  'code',
  'vision',
  'embedding',
  'rerank',
]);
export type Capability = z.infer<typeof capabilitySchema>;

export const resourceProfileSchema = z.object({
  memory_gb: z.number().positive(),
  context_length: z.number().int().positive(),
});

export const modelSchema = z.object({
  // Internal UUID. Never exposed on the public gateway; the admin API needs a
  // stable handle and `alias` is user-editable, so it is carried here.
  id: z.string(),
  alias: z.string(),
  ref: z.string(),
  runtime: runtimeKindSchema,
  node_id: z.string(),
  state: modelStateSchema,
  capabilities: z.array(capabilitySchema),
  resource_profile: resourceProfileSchema,
});
export type Model = z.infer<typeof modelSchema>;

export const modelListSchema = z.array(modelSchema);

/**
 * `ref` is passed to a runtime adapter, so it is constrained here as well as
 * server-side (ARCHITECTURE.md section 2.2, security.md "no shell string
 * construction"). The client check is a convenience; the server owns the rule.
 */
const REF_PATTERN = /^[A-Za-z0-9._:/-]+$/;

export const createModelSchema = z.object({
  alias: z
    .string()
    .min(1, 'Required')
    .max(64)
    .regex(/^[a-z0-9-]+$/, 'Lower case letters, digits and hyphens only.'),
  ref: z
    .string()
    .min(1, 'Required')
    .regex(REF_PATTERN, 'Contains characters a runtime reference cannot hold.'),
  runtime: runtimeKindSchema,
  node_id: z.string().min(1, 'Choose a node.'),
  capabilities: z
    .array(capabilitySchema)
    .min(1, 'Choose at least one capability.'),
  // Coerced because number inputs hand back strings.
  resource_profile: z.object({
    memory_gb: z.coerce.number().positive(),
    context_length: z.coerce.number().int().positive(),
  }),
});
// `z.coerce` above means the form holds strings and only becomes numbers
// after parsing, so the input and output types are genuinely different.
// react-hook-form takes both; collapsing them to `z.infer` (the output type)
// would claim the form already holds parsed values and break the resolver.
export type CreateModelInput = z.input<typeof createModelSchema>;
export type CreateModelValues = z.output<typeof createModelSchema>;

export const updateModelSchema = createModelSchema.partial();
export type UpdateModelInput = z.input<typeof updateModelSchema>;

/** Progress for a download job, polled through `refetchInterval`. */
export const downloadJobSchema = z.object({
  job_id: z.string(),
  model_id: z.string(),
  state: z.enum(['queued', 'running', 'succeeded', 'failed']),
  /** 0 to 1. Absent while the runtime has not reported a total yet. */
  progress: z.number().min(0).max(1).nullable(),
  bytes_downloaded: z.number().int().nonnegative().nullable(),
  bytes_total: z.number().int().nonnegative().nullable(),
  message: z.string().nullable(),
});
export type DownloadJob = z.infer<typeof downloadJobSchema>;

/**
 * Compute nodes. The read shape lives here because the model form's node
 * dropdown needs it; the write side (register, edit, delete, health check) is
 * `features/nodes`, which shipped in Phase 2 alongside the SSRF guard, since a
 * node record is an address the platform makes outbound requests to
 * (security.md section 7.2).
 */
export const nodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  address: z.string(),
  status: z.enum(['online', 'offline', 'degraded']),
  total_memory_gb: z.number(),
  runtimes: z.array(runtimeKindSchema),
});
export type Node = z.infer<typeof nodeSchema>;

export const nodeListSchema = z.array(nodeSchema);

export const RUNTIME_LABELS: Record<RuntimeKind, string> = {
  ollama: 'Ollama',
  mlx: 'MLX',
  vllm: 'vLLM',
  llamacpp: 'llama.cpp',
};
