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
});
export type ChatRequest = z.infer<typeof chatRequestSchema>;

export const composerSchema = z.object({
  capability: capabilitySchema,
  prompt: z.string().min(1, 'Say something.'),
});
export type ComposerInput = z.infer<typeof composerSchema>;

/**
 * One decoded SSE frame. `admin_chat.py` may use a simpler shape than the
 * OpenAI-compatible gateway (backend.md section 6), so the reader accepts
 * several spellings of the same thing and this stays permissive.
 */
export const streamFrameSchema = z.object({
  delta: z.string().optional(),
  content: z.string().optional(),
  finish_reason: z.string().nullish(),
  error: z
    .union([z.string(), z.object({ message: z.string().optional() })])
    .optional(),
  type: z.string().optional(),
  usage: z
    .object({
      prompt_tokens: z.number().optional(),
      completion_tokens: z.number().optional(),
    })
    .optional(),
});
export type StreamFrame = z.infer<typeof streamFrameSchema>;
