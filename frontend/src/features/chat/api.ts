import { apiRequest } from '@/lib/api-client';
import type { ChatRequest } from '@/features/chat/schema';

/**
 * Opens the SSE stream. The AbortSignal is passed straight through to `fetch`:
 * without it the backend keeps generating and holds a concurrency slot after
 * the user has navigated away. This is the client half of the disconnect
 * guardrail in security.md section 4.3.
 */
export function openChatStream(
  request: ChatRequest,
  signal: AbortSignal,
): Promise<Response> {
  return apiRequest('/chat', {
    method: 'POST',
    body: request,
    signal,
    headers: { Accept: 'text/event-stream' },
  });
}
