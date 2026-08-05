import { z } from 'zod';

/**
 * Mirrors the backend's `PromptTemplateResponse`, and checked against it by
 * `lib/api-contract.ts` rather than by anyone remembering to keep the two in
 * step.
 *
 * **There is no variable substitution and none is coming.** The reason is in
 * `domain/entities/prompt_template.py` and it is a boundary rather than a
 * simplification: a slot filled from a request would let a caller write into
 * the one message the model treats as authoritative. What a caller chooses is
 * *which* template, out of the set their tenant authored.
 */

export const promptTemplateSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  /** Shown in full. Not a secret — every account holds `prompt:read`, because
   *  choosing between templates without seeing what they say is choosing
   *  blind, and a template shapes every answer that selects it. */
  system_prompt: z.string(),
  /** Nullable because the API is: the column is `NOT NULL`, but an entity not
   *  yet read back has no timestamp. The create path reads back, so in
   *  practice these arrive set; accepting null is what stops a future path
   *  that forgets from throwing here instead of showing a row. */
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
});
export type PromptTemplate = z.infer<typeof promptTemplateSchema>;

export const promptTemplateListSchema = z.array(promptTemplateSchema);

/** Restated from `MAX_SYSTEM_PROMPT_CHARS`, so the field's counter and the
 *  server's refusal agree about the number the operator is typing against. */
export const MAX_SYSTEM_PROMPT_CHARS = 8000;

export const promptTemplateFormSchema = z.object({
  name: z
    .string()
    .min(1, 'Required')
    .max(128)
    // The name is what a caller writes in `"prompt_template": "..."`, so it
    // travels in JSON written by hand. Leading or trailing space in a value
    // like that is a bug report about a template that "does not exist".
    .refine((v) => v === v.trim(), 'No leading or trailing spaces'),
  description: z.string().max(1024),
  system_prompt: z
    .string()
    .min(1, 'A template needs a system prompt')
    .max(MAX_SYSTEM_PROMPT_CHARS, `At most ${MAX_SYSTEM_PROMPT_CHARS} characters`),
});
export type PromptTemplateFormValues = z.infer<typeof promptTemplateFormSchema>;
