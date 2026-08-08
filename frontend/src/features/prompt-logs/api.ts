import { api } from '@/lib/api-client';
import {
  promptLogListSchema,
  promptLogTranscriptSchema,
  type PromptLogFilters,
  type PromptLogPage,
  type PromptLogTranscript,
} from '@/features/prompt-logs/schema';

const BASE = '/prompt-logs';

export async function listPromptLogs(filters: PromptLogFilters): Promise<PromptLogPage> {
  return promptLogListSchema.parse(
    await api.get<unknown>(BASE, {
      query: {
        capability: filters.capability || undefined,
        request_id: filters.request_id || undefined,
        limit: filters.limit,
        offset: filters.offset,
      },
    }),
  );
}

/**
 * The audited one. Every call to this writes a `prompt_log.read` row naming
 * the transcript, so it must be reached by a deliberate action and never from
 * a prefetch, a hover, or a list render — an audit trail whose entries were
 * produced by the UI moving the mouse describes nothing.
 */
export async function getPromptLogTranscript(id: string): Promise<PromptLogTranscript> {
  return promptLogTranscriptSchema.parse(await api.get<unknown>(`${BASE}/${id}`));
}
