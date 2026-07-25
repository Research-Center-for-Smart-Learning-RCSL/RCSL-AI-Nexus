import { describe, expect, it, vi } from 'vitest';

import { readChatStream, type StreamHandlers } from '@/features/chat/stream';

/** A Response whose body streams the given chunks verbatim, then closes. */
function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream);
}

function collectingHandlers(): {
  handlers: StreamHandlers;
  deltas: string[];
  errors: string[];
  done: () => number;
} {
  const deltas: string[] = [];
  const errors: string[] = [];
  const onDone = vi.fn();
  return {
    deltas,
    errors,
    done: () => onDone.mock.calls.length,
    handlers: {
      onDelta: (text) => deltas.push(text),
      onError: (message) => errors.push(message),
      onDone,
    },
  };
}

const frame = (obj: unknown) => `data: ${JSON.stringify(obj)}\n\n`;
const delta = (content: string) => frame({ choices: [{ delta: { content } }] });

describe('readChatStream', () => {
  it('emits each delta then completes on the done sentinel', async () => {
    const c = collectingHandlers();
    await readChatStream(sseResponse([delta('Hel'), delta('lo'), 'data: [DONE]\n\n']), c.handlers);
    expect(c.deltas).toEqual(['Hel', 'lo']);
    expect(c.done()).toBe(1);
    expect(c.errors).toEqual([]);
  });

  it('reassembles a frame split across chunk boundaries', async () => {
    const c = collectingHandlers();
    await readChatStream(
      sseResponse(['data: {"choices":[{"delta":{"content":"ab', 'cd"}}]}\n\n', 'data: [DONE]\n\n']),
      c.handlers,
    );
    expect(c.deltas).toEqual(['abcd']);
  });

  it('accepts CRLF event boundaries', async () => {
    const c = collectingHandlers();
    const crlf = `data: ${JSON.stringify({ choices: [{ delta: { content: 'hi' } }] })}\r\n\r\n`;
    await readChatStream(sseResponse([crlf, 'data: [DONE]\r\n\r\n']), c.handlers);
    expect(c.deltas).toEqual(['hi']);
    expect(c.done()).toBe(1);
  });

  it('completes on a finish_reason without a sentinel', async () => {
    const c = collectingHandlers();
    await readChatStream(
      sseResponse([delta('done'), frame({ choices: [{ finish_reason: 'stop' }] })]),
      c.handlers,
    );
    expect(c.deltas).toEqual(['done']);
    expect(c.done()).toBe(1);
    expect(c.errors).toEqual([]);
  });

  it('surfaces a terminal error frame (object form) as a first-class outcome', async () => {
    const c = collectingHandlers();
    await readChatStream(sseResponse([frame({ error: { message: 'model exploded' } })]), c.handlers);
    expect(c.errors).toEqual(['model exploded']);
    expect(c.done()).toBe(0);
  });

  it('surfaces the string form of an error frame', async () => {
    const c = collectingHandlers();
    await readChatStream(sseResponse([frame({ error: 'nope' })]), c.handlers);
    expect(c.errors).toEqual(['nope']);
  });

  it('reports a malformed (unparseable) frame', async () => {
    const c = collectingHandlers();
    await readChatStream(sseResponse(['data: not-json\n\n']), c.handlers);
    expect(c.errors).toEqual(['Received a malformed frame.']);
  });

  it('reports an unrecognised (schema-invalid) frame', async () => {
    const c = collectingHandlers();
    await readChatStream(sseResponse(['data: 5\n\n']), c.handlers);
    expect(c.errors).toEqual(['Received an unrecognised frame.']);
  });

  it('reports a truncated stream that closes without a terminator', async () => {
    const c = collectingHandlers();
    await readChatStream(sseResponse([delta('hi')]), c.handlers);
    expect(c.deltas).toEqual(['hi']);
    expect(c.errors).toEqual(['The connection closed before the response ended.']);
  });

  it('treats an aborted stream as a completion, not a failure', async () => {
    const c = collectingHandlers();
    const controller = new AbortController();
    controller.abort();
    await readChatStream(sseResponse([]), c.handlers, controller.signal);
    expect(c.errors).toEqual([]);
    expect(c.done()).toBe(1);
  });

  it('reports a response with no body', async () => {
    const c = collectingHandlers();
    await readChatStream(new Response(null), c.handlers);
    expect(c.errors).toEqual(['The server sent no response body.']);
  });
});
