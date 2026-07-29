/**
 * SSE reader for `/admin/chat`, and for `/admin/assistant`, which frames its
 * answer identically.
 *
 * The subtle part is the terminal error frame. By the time generation fails,
 * the HTTP status has already been sent, so the response is a 200 with a
 * truncated body (backend.md section 6). A reader that only checks
 * `response.ok` reports success and silently drops the tail. This one treats an
 * error frame as a first-class outcome and hands the message to the caller.
 *
 * Shared rather than copied for the assistant. Two readers would be two places
 * for the error-frame handling above to be got right, and the second one would
 * be written by someone who had not yet had the failure that produced the
 * first. It stays in `features/chat` because that is the endpoint whose shape
 * it describes and where its tests live; the assistant imports it.
 */

import {
  frameFinishReason,
  frameReasoning,
  frameText,
  streamFrameSchema,
  type StreamFrame,
} from '@/features/chat/schema';

export const DONE_SENTINEL = '[DONE]';

export type StreamHandlers = {
  onDelta: (text: string) => void;
  /**
   * Reasoning from a thinking model. Optional, so a caller that has no place
   * to show it simply drops it rather than mixing it into the answer.
   */
  onReasoning?: (text: string) => void;
  /** Terminal error frame, or a stream that ended without a done sentinel. */
  onError: (message: string) => void;
  /**
   * The reason carried by the terminal frame, when there was one.
   *
   * Passed on rather than discarded: `length` means the platform's ceiling cut
   * the generation, and a thinking model can reach it having produced no answer
   * at all. Dropping it made that outcome indistinguishable from a normal
   * completion that happened to be empty — the same blank bubble either way,
   * with nothing on screen to say the model was still working when it stopped.
   */
  onDone: (finishReason?: string | null) => void;
  /**
   * A frame this reader has no interpretation for, handed over undecoded.
   *
   * Providing it also changes when the read ends, and the two belong together:
   * a trailer is emitted *after* the terminal `finish_reason` frame and before
   * `[DONE]` (backend `interfaces/http/sse.py`), so a caller expecting one must
   * read on to the sentinel rather than stopping at the reason. Without this
   * handler the reader keeps its existing behaviour and returns at the reason,
   * which is what every chat turn wants.
   *
   * Undecoded because this module should not learn the shape of every feature's
   * extra frames. The assistant's proposal is validated in `features/assistant`
   * against its own schema, which matters: `streamFrameSchema` strips unknown
   * keys rather than rejecting them, so a trailer parsed through it would
   * arrive as an empty object — the same silent failure that once made the chat
   * panel render nothing at all.
   */
  onTrailer?: (raw: unknown) => void;
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
  // Held rather than reported immediately, but only for a caller that reads
  // past it. It still reaches `onDone`, just at the sentinel instead.
  let heldFinishReason: string | null = null;

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
            handlers.onDone(heldFinishReason ?? undefined);
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

          const reasoning = frameReasoning(frame.data);
          if (reasoning) handlers.onReasoning?.(reasoning);

          const delta = extractDelta(frame.data);
          if (delta) handlers.onDelta(delta);

          const finishReason = frameFinishReason(frame.data);
          if (finishReason) {
            if (!handlers.onTrailer) {
              sawTerminator = true;
              handlers.onDone(finishReason);
              return;
            }
            // A caller expecting a trailer reads on: the trailer is emitted
            // after this frame. The reason is not lost, only deferred to the
            // sentinel below.
            heldFinishReason = finishReason;
            continue;
          }

          // Anything left is a frame this reader does not model. Offered
          // undecoded, and only to a caller that asked, so the chat panel never
          // sees a frame it has no idea what to do with.
          if (handlers.onTrailer && !reasoning && !delta) {
            handlers.onTrailer(parsed);
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
