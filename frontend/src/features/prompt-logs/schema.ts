import { z } from 'zod';

/**
 * Prompt transcripts, from `/admin/prompt-logs`. Read-only, admin-only, and
 * the most sensitive data this UI ever renders.
 *
 * These rows exist only because somebody opened a debug window on an API key
 * or a user account (security.md section 9.2). By default the platform records
 * metadata and nothing else, so on an ordinary deployment this list is empty —
 * which is the correct and expected state, not a broken screen.
 *
 * **Two schemas, because there are two responses and the difference is the
 * whole design.** The summary carries no message content at all: the list
 * exists to let an operator find the one conversation they need. Reading that
 * conversation is a second request, and the server writes an audit row naming
 * it. So opening this screen discloses nothing and records nothing; opening a
 * transcript does both.
 */

export const promptLogSummarySchema = z.object({
  id: z.string(),
  at: z.string(),
  actor_id: z.string(),
  api_key_id: z.string().nullable(),
  capability: z.string(),
  model_alias: z.string(),
  request_id: z.string().nullable(),
  finish_reason: z.string().nullable(),
  completed: z.boolean(),
  tool_calls: z.number().int().nonnegative(),
  message_chars: z.number().int().nonnegative(),
  completion_chars: z.number().int().nonnegative(),
  reasoning_chars: z.number().int().nonnegative(),
  truncated_fields: z.array(z.string()),
});

export const promptLogListSchema = z.object({
  entries: z.array(promptLogSummarySchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
});

export const promptLogTranscriptSchema = promptLogSummarySchema
  .omit({ message_chars: true, completion_chars: true, reasoning_chars: true })
  .extend({
    messages: z.string(),
    completion: z.string(),
    reasoning: z.string(),
  });

export type PromptLogSummary = z.infer<typeof promptLogSummarySchema>;
export type PromptLogPage = z.infer<typeof promptLogListSchema>;
export type PromptLogTranscript = z.infer<typeof promptLogTranscriptSchema>;

export type PromptLogFilters = {
  capability?: string;
  request_id?: string;
  limit: number;
  offset: number;
};

/**
 * One turn of a stored conversation, as the backend serialised it.
 *
 * `messages` arrives as a JSON *string* rather than a nested object, and it
 * stays one across the wire deliberately: the column is opaque text that
 * nothing queries into, and a shape declared on both sides would be a third
 * place for the `Message` entity to drift. It is parsed here, at the one point
 * that renders it, and a string that does not parse is shown raw rather than
 * throwing — a transcript that is hard to read still beats an error where the
 * evidence should be.
 */
export type TranscriptTurn = {
  role: string;
  content: string;
  name?: string;
  tool_call_id?: string;
  tool_calls?: { id: string; name: string; arguments: string }[];
};

export function parseTranscriptTurns(messages: string): TranscriptTurn[] | null {
  try {
    const parsed: unknown = JSON.parse(messages);
    if (!Array.isArray(parsed)) return null;
    return parsed as TranscriptTurn[];
  } catch {
    return null;
  }
}
