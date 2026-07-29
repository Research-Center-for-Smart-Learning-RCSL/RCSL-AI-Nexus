import { apiRequest } from '@/lib/api-client';
import type { AssistRequest } from '@/features/assistant/schema';

/**
 * Opens the assistant's SSE stream.
 *
 * The AbortSignal is passed straight to `fetch`, for the same reason the chat
 * panel does it: without it the backend keeps generating and holds a
 * concurrency slot after the drawer has been closed. A drawer is closed far
 * more casually than a page is navigated away from, so this matters more here,
 * not less.
 */
export function openAssistantStream(
  request: AssistRequest,
  signal: AbortSignal,
): Promise<Response> {
  return apiRequest('/assistant', {
    method: 'POST',
    body: request,
    signal,
    headers: { Accept: 'text/event-stream' },
  });
}
