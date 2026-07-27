import { z } from 'zod';

import { capabilitySchema } from '@/features/models/schema';

export const chatRoleSchema = z.enum(['system', 'user', 'assistant']);
export type ChatRole = z.infer<typeof chatRoleSchema>;

export const chatMessageSchema = z.object({
  role: chatRoleSchema,
  content: z.string(),
});
export type ChatMessage = z.infer<typeof chatMessageSchema>;

/**
 * The admin chat endpoint reuses `RouteChatRequest` but authorises by user
 * identity rather than an API key (ARCHITECTURE.md section 3), so the request
 * names a capability rather than a model.
 */
export const chatRequestSchema = z.object({
  capability: capabilitySchema,
  messages: z.array(chatMessageSchema).min(1),
  /** Clamped server-side by the per-request hard cap (security.md 4.3). */
  max_tokens: z.number().int().positive().optional(),
  /**
   * Omitted takes the deployment default. `false` asks a deliberating model to
   * answer directly — the difference between an answer and none on a question
   * the model will not stop reasoning about. Not clamped server-side, unlike
   * `max_tokens`: it asks for less work, not more.
   */
  think: z.boolean().optional(),
});
export type ChatRequest = z.infer<typeof chatRequestSchema>;

export const composerSchema = z.object({
  capability: capabilitySchema,
  prompt: z.string().min(1, 'Say something.'),
});
export type ComposerInput = z.infer<typeof composerSchema>;

/**
 * One decoded SSE frame.
 *
 * The backend sends the OpenAI envelope, `{choices: [{delta: {content}}]}`.
 * An earlier version of this schema described a flat `{delta?, content?}`
 * shape instead, and because zod strips unknown keys rather than rejecting
 * them, every real frame parsed *successfully* into an empty object. The
 * result was a chat that appended the user's turn, received `[DONE]`, and
 * silently rendered no reply at all, with no error anywhere.
 *
 * So the envelope is described explicitly, and the flat spelling is kept
 * alongside it for `admin_chat.py`, which backend.md section 6 says may frame
 * things more simply.
 */
const openAiChoiceSchema = z.object({
  index: z.number().optional(),
  delta: z
    .object({
      role: z.string().optional(),
      content: z.string().optional(),
      /**
       * A thinking model's deliberation, which the backend deliberately keeps
       * out of `content`. Parsed as its own field for the same reason: it is
       * shown separately and never becomes part of the reply that gets sent
       * back as history.
       */
      reasoning_content: z.string().optional(),
    })
    .optional(),
  finish_reason: z.string().nullish(),
});

export const streamFrameSchema = z.object({
  choices: z.array(openAiChoiceSchema).optional(),
  // Flat spelling, for a simpler framer.
  delta: z.string().optional(),
  content: z.string().optional(),
  finish_reason: z.string().nullish(),
  error: z.union([z.string(), z.object({ message: z.string().optional() })]).optional(),
  type: z.string().optional(),
  usage: z
    .object({
      prompt_tokens: z.number().optional(),
      completion_tokens: z.number().optional(),
    })
    .optional(),
});
export type StreamFrame = z.infer<typeof streamFrameSchema>;

/** Text carried by a frame, in whichever spelling it arrived. */
export function frameText(frame: StreamFrame): string {
  const fromEnvelope = frame.choices?.[0]?.delta?.content;
  return fromEnvelope ?? frame.delta ?? frame.content ?? '';
}

/** Reasoning carried by a frame. Empty for every non-thinking model. */
export function frameReasoning(frame: StreamFrame): string {
  return frame.choices?.[0]?.delta?.reasoning_content ?? '';
}

export function frameFinishReason(frame: StreamFrame): string | null {
  return frame.choices?.[0]?.finish_reason ?? frame.finish_reason ?? null;
}
