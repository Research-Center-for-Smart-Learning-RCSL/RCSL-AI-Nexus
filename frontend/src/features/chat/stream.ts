/**
 * SSE reader for `/admin/chat`.
 *
 * The subtle part is the terminal error frame. By the time generation fails,
 * the HTTP status has already been sent, so the response is a 200 with a
 * truncated body (backend.md section 6). A reader that only checks
 * `response.ok` reports success and silently drops the tail. This one treats an
 * error frame as a first-class outcome and hands the message to the caller.
 */

import {
  frameFinishReason,
  frameText,
  streamFrameSchema,
  type StreamFrame,
} from '@/features/chat/schema';

export const DONE_SENTINEL = '[DONE]';

export type StreamHandlers = {
  onDelta: (text: string) => void;
  /** Terminal error frame, or a stream that ended without a done sentinel. */
  onError: (message: string) => void;
  onDone: () => void;
};

// Reading the envelope is the schema's job, so both spellings resolve here.
const extractDelta = frameText;

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

/** First event boundary in the buffer, in either LF or CRLF spelling. */
function nextBoundary(buffer: string): { index: number; length: number } | null {
  const lf = buffer.indexOf('\n\n');
  const crlf = buffer.indexOf('\r\n\r\n');
  if (crlf !== -1 && (lf === -1 || crlf < lf)) return { index: crlf, length: 4 };
  if (lf !== -1) return { index: lf, length: 2 };
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
      //
      // Both spellings are accepted. The current framer emits `\n\n`, but the
      // spec permits CRLF and sse-starlette uses it, so matching only on LF
      // would leave the buffer growing until the response ended and then
      // report a truncation. That failure only appears when the server-side
      // framer is swapped, which is exactly when nobody would look here.
      let boundary = nextBoundary(buffer);
      while (boundary !== null) {
        const block = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary.length);
        boundary = nextBoundary(buffer);

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

          if (frameFinishReason(frame.data)) {
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
    // Cancel, not just release. Every early return above (the `[DONE]`
    // sentinel, a finish_reason, an error frame) leaves unread bytes on the
    // wire; releasing the lock alone keeps the connection alive until garbage
    // collection. Cancelling can itself throw if the body is already gone,
    // which is not worth failing a completed stream over.
    try {
      await reader.cancel();
    } catch {
      // already closed
    }
    reader.releaseLock();
  }
}
