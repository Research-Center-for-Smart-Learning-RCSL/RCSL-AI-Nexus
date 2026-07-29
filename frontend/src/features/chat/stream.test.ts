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

describe('readChatStream with a thinking model', () => {
  const reasoning = (text: string) =>
    frame({ choices: [{ delta: { reasoning_content: text } }] });

  /** Like collectingHandlers, plus the reasoning channel. */
  function thinkingHandlers() {
    const deltas: string[] = [];
    const thoughts: string[] = [];
    const errors: string[] = [];
    const onDone = vi.fn();
    return {
      deltas,
      thoughts,
      errors,
      done: () => onDone.mock.calls.length,
      handlers: {
        onDelta: (text: string) => deltas.push(text),
        onReasoning: (text: string) => thoughts.push(text),
        onError: (message: string) => errors.push(message),
        onDone,
      } satisfies StreamHandlers,
    };
  }

  it('routes reasoning to its own handler and keeps it out of the answer', async () => {
    const c = thinkingHandlers();
    await readChatStream(
      sseResponse([reasoning('let me think'), delta('42'), 'data: [DONE]\n\n']),
      c.handlers,
    );

    expect(c.thoughts).toEqual(['let me think']);
    expect(c.deltas).toEqual(['42']);
    expect(c.done()).toBe(1);
  });

  it('reports a generation that produced only reasoning', async () => {
    // The 2026-07-27 case: the whole token budget went to deliberation and the
    // model never started an answer. That is a finished stream with no content,
    // not an error, and the reasoning is the only thing there is to show.
    const c = thinkingHandlers();
    await readChatStream(
      sseResponse([
        reasoning('still working'),
        frame({ choices: [{ delta: {}, finish_reason: 'length' }] }),
      ]),
      c.handlers,
    );

    expect(c.thoughts).toEqual(['still working']);
    expect(c.deltas).toEqual([]);
    expect(c.errors).toEqual([]);
    expect(c.done()).toBe(1);
  });

  it('drops reasoning silently when the caller has nowhere to show it', async () => {
    // onReasoning is optional, so the gateway-facing reader stays unchanged.
    const deltas: string[] = [];
    const onDone = vi.fn();
    await readChatStream(sseResponse([reasoning('ignored'), delta('hi'), 'data: [DONE]\n\n']), {
      onDelta: (text) => deltas.push(text),
      onError: () => {},
      onDone,
    });

    expect(deltas).toEqual(['hi']);
    expect(onDone).toHaveBeenCalledOnce();
  });
});

describe('the terminal frame reason', () => {
  it('reaches onDone instead of being discarded', async () => {
    // `length` is the platform's ceiling reporting itself. The reader read it,
    // branched on it, and dropped it, so the UI could not tell a truncated
    // generation from a complete one that produced nothing.
    const reasons: (string | null | undefined)[] = [];
    await readChatStream(
      sseResponse([
        delta('partial'),
        frame({ choices: [{ delta: {}, finish_reason: 'length' }] }),
      ]),
      { onDelta: () => {}, onError: () => {}, onDone: (r) => reasons.push(r) },
    );

    expect(reasons).toEqual(['length']);
  });

  it('passes nothing when the stream ended on the done sentinel', async () => {
    const reasons: (string | null | undefined)[] = [];
    await readChatStream(sseResponse([delta('hi'), 'data: [DONE]\n\n']), {
      onDelta: () => {},
      onError: () => {},
      onDone: (r) => reasons.push(r),
    });

    expect(reasons).toEqual([undefined]);
  });
});

describe('a caller that expects a trailer', () => {
  const terminal = frame({ choices: [{ delta: {}, finish_reason: 'stop' }] });
  const proposal = frame({ proposal: { action: 'create' } });

  it('reads past the finish_reason to reach frames that follow it', async () => {
    // The whole reason the option exists. The backend emits the trailer after
    // the terminal frame and before the sentinel, so a reader that stopped at
    // the reason — which is what every chat turn wants — would never see it.
    const trailers: unknown[] = [];
    await readChatStream(sseResponse([delta('hi'), terminal, proposal, 'data: [DONE]\n\n']), {
      onDelta: () => {},
      onError: () => {},
      onDone: () => {},
      onTrailer: (raw) => trailers.push(raw),
    });

    expect(trailers).toEqual([{ proposal: { action: 'create' } }]);
  });

  it('still reports the finish_reason, deferred to the sentinel', async () => {
    const reasons: (string | null | undefined)[] = [];
    await readChatStream(sseResponse([delta('hi'), frame({ choices: [{ delta: {}, finish_reason: 'length' }] }), 'data: [DONE]\n\n']), {
      onDelta: () => {},
      onError: () => {},
      onDone: (r) => reasons.push(r),
      onTrailer: () => {},
    });

    expect(reasons).toEqual(['length']);
  });

  it('hands over the frame undecoded, so the caller validates it', async () => {
    // `streamFrameSchema` strips unknown keys rather than rejecting them, so a
    // trailer routed through it would arrive as `{}` — the same silent failure
    // that once made the chat panel render every reply as nothing at all.
    const trailers: unknown[] = [];
    await readChatStream(
      sseResponse([frame({ proposal: { action: 'update', key_id: 'abc' } }), 'data: [DONE]\n\n']),
      {
        onDelta: () => {},
        onError: () => {},
        onDone: () => {},
        onTrailer: (raw) => trailers.push(raw),
      },
    );

    expect(trailers).toEqual([{ proposal: { action: 'update', key_id: 'abc' } }]);
  });

  it('is not offered content frames', async () => {
    const trailers: unknown[] = [];
    await readChatStream(sseResponse([delta('hi'), 'data: [DONE]\n\n']), {
      onDelta: () => {},
      onError: () => {},
      onDone: () => {},
      onTrailer: (raw) => trailers.push(raw),
    });

    expect(trailers).toEqual([]);
  });

  it('gets no trailer from a stream that failed', async () => {
    // The backend withholds it on error for the same reason it withholds
    // `[DONE]`, and the reader must not invent one from a frame that arrived
    // before the failure.
    const trailers: unknown[] = [];
    const errors: string[] = [];
    await readChatStream(
      sseResponse([delta('partial'), frame({ error: { message: 'model exploded' } })]),
      {
        onDelta: () => {},
        onError: (m) => errors.push(m),
        onDone: () => {},
        onTrailer: (raw) => trailers.push(raw),
      },
    );

    expect(errors).toEqual(['model exploded']);
    expect(trailers).toEqual([]);
  });
});
