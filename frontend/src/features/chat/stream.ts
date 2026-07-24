/**
 * SSE reader for `/admin/chat`.
 *
 * The subtle part is the terminal error frame. By the time generation fails,
 * the HTTP status has already been sent, so the response is a 200 with a
 * truncated body (backend.md section 6). A reader that only checks
 * `response.ok` reports success and silently drops the tail. This one treats an
 * error frame as a first-class outcome and hands the message to the caller.
 */

import { streamFrameSchema, type StreamFrame } from '@/features/chat/schema';

export const DONE_SENTINEL = '[DONE]';

export type StreamHandlers = {
  onDelta: (text: string) => void;
  /** Terminal error frame, or a stream that ended without a done sentinel. */
  onError: (message: string) => void;
  onDone: () => void;
};

function extractDelta(frame: StreamFrame): string {
  if (typeof frame.delta === 'string') return frame.delta;
  if (typeof frame.content === 'string') return frame.content;
  return '';
}

function extractError(frame: StreamFrame): string | null {
  if (frame.type === 'error') {
    if (typeof frame.error === 'string') return frame.error;
    return frame.error?.message ?? 'The model stopped unexpectedly.';
  }
  if (typeof frame.error === 'string') return frame.error;
  if (frame.error && typeof frame.error === 'object') {
    return frame.error.message ?? 'The model stopped unexpectedly.';
  }
  return null;
}

/** Pulls `data:` payloads out of one SSE event block. */
function dataLines(block: string): string[] {
  const out: string[] = [];
  for (const line of block.split('\n')) {
    const trimmed = line.trimEnd();
    if (trimmed.startsWith('data:')) out.push(trimmed.slice(5).trimStart());
  }
  return out;
}

/**
 * Consumes the response body to exhaustion or until the signal aborts.
 * Resolves once the stream is finished; never throws for a mid-stream failure,
 * which arrives through `onError` instead.
 */
export async function readChatStream(
  response: Response,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const body = response.body;
  if (!body) {
    handlers.onError('The server sent no response body.');
    return;
  }

  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let sawTerminator = false;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by a blank line. Anything after the last
      // separator is a partial event and stays in the buffer.
      let separator = buffer.indexOf('\n\n');
      while (separator !== -1) {
        const block = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        separator = buffer.indexOf('\n\n');

        for (const payload of dataLines(block)) {
          if (!payload) continue;
          if (payload === DONE_SENTINEL) {
            sawTerminator = true;
            handlers.onDone();
            return;
          }

          let parsed: unknown;
          try {
            parsed = JSON.parse(payload);
          } catch {
            // A frame we cannot decode is a protocol failure, not a delta.
            // Surfacing it beats appending JSON noise to the transcript.
            sawTerminator = true;
            handlers.onError('Received a malformed frame.');
            return;
          }

          const frame = streamFrameSchema.safeParse(parsed);
          if (!frame.success) {
            sawTerminator = true;
            handlers.onError('Received an unrecognised frame.');
            return;
          }

          const failure = extractError(frame.data);
          if (failure) {
            sawTerminator = true;
            handlers.onError(failure);
            return;
          }

          const delta = extractDelta(frame.data);
          if (delta) handlers.onDelta(delta);

          if (frame.data.finish_reason) {
            sawTerminator = true;
            handlers.onDone();
            return;
          }
        }
      }
    }

    // Reaching here means the connection closed without a terminator. That is
    // a truncation, so it is reported rather than passed off as a completion.
    if (!sawTerminator) {
      if (signal?.aborted) handlers.onDone();
      else handlers.onError('The connection closed before the response ended.');
    }
  } catch (caught) {
    // An abort is a user action, not a failure.
    if (
      signal?.aborted ||
      (caught instanceof DOMException && caught.name === 'AbortError')
    ) {
      handlers.onDone();
      return;
    }
    handlers.onError(
      caught instanceof Error ? caught.message : 'The stream failed.',
    );
  } finally {
    // Releases the lock so the body can be cancelled by the abort controller.
    reader.releaseLock();
  }
}
