import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { createElement, type ReactNode } from 'react';

import { useAssistant } from '@/features/assistant/hooks/use-assistant';
import { AssistantContextProvider } from '@/features/assistant/context';
import { openAssistantStream } from '@/features/assistant/api';

vi.mock('@/features/assistant/api', () => ({ openAssistantStream: vi.fn() }));

/**
 * What happens to a running answer when the operator stops or clears.
 *
 * The assistant accumulates its answer in a local variable rather than reading
 * it back out of the stream store, so — unlike `useChatStream`, which is
 * protected by `clear` resetting that store — nothing here makes the in-flight
 * turn disappear on its own. It has to be retired explicitly.
 */

function wrapper({ children }: { children: ReactNode }) {
  return createElement(AssistantContextProvider, null, children);
}

/** A response whose body stays open until `push`/`close` are called. */
function controllable() {
  let controller: ReadableStreamDefaultController<Uint8Array>;
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body),
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    close: () => controller.close(),
  };
}

const delta = (content: string) =>
  `data: ${JSON.stringify({ choices: [{ delta: { content } }] })}\n\n`;

async function startAnswering() {
  const stream = controllable();
  vi.mocked(openAssistantStream).mockResolvedValue(stream.response);
  const { result } = renderHook(() => useAssistant(), { wrapper });

  await act(async () => {
    void result.current.send('which key should I revoke?');
  });
  await act(async () => {
    stream.push(delta('Revoke the one'));
  });
  return { result, stream };
}

describe('clearing while an answer is streaming', () => {
  // The transcript is restored from sessionStorage on mount, so without this a
  // test inherits the previous one's turns. That it needs clearing at all is
  // the persistence working.
  beforeEach(() => window.sessionStorage.clear());

  it('does not let the in-flight turn reappear in the transcript it emptied', async () => {
    // Clear is enabled mid-stream, so this is the ordinary path rather than a
    // race. The answer lives in a local, so without retiring the generation the
    // `finally` appended it into the list `clear` had just emptied — and wrote
    // that orphan to sessionStorage, where it survived a reload.
    const { result, stream } = await startAnswering();
    expect(result.current.turns).toHaveLength(1);

    await act(async () => {
      result.current.clear();
    });
    await act(async () => {
      stream.close();
    });

    expect(result.current.turns).toEqual([]);
    expect(result.current.isStreaming).toBe(false);
  });

  it('keeps a partial answer when the operator merely stops it', async () => {
    // The distinction the counter has to preserve: Stop keeps what the hardware
    // produced, because that is also what was billed. Only Clear discards it,
    // and only because an empty transcript is what was asked for.
    const { result, stream } = await startAnswering();

    await act(async () => {
      result.current.cancel();
    });
    await act(async () => {
      stream.close();
    });

    expect(result.current.turns.map((t) => t.content)).toEqual([
      'which key should I revoke?',
      'Revoke the one',
    ]);
  });

  it('records nothing for a generation stopped before its first token', async () => {
    // Cancelling immediately would otherwise leave an empty Assistant bubble,
    // and report the abort as "The answer stopped: signal is aborted without
    // reason" — a description of the implementation rather than of anything the
    // operator did.
    const stream = controllable();
    vi.mocked(openAssistantStream).mockResolvedValue(stream.response);
    const { result } = renderHook(() => useAssistant(), { wrapper });

    await act(async () => {
      void result.current.send('anything');
    });
    await act(async () => {
      result.current.cancel();
    });
    await act(async () => {
      stream.close();
    });

    expect(result.current.turns.map((t) => t.role)).toEqual(['user']);
  });
});

describe('stopping before the response headers arrive', () => {
  beforeEach(() => window.sessionStorage.clear());

  it('is a cancellation, not a failure', async () => {
    // The abort reaches `fetch` rather than the reader, so it rejects the call
    // instead of ending the stream. Reported as an error it read "The answer
    // stopped: signal is aborted without reason", which describes the
    // implementation rather than anything the operator did.
    vi.mocked(openAssistantStream).mockRejectedValue(
      new DOMException('signal is aborted without reason', 'AbortError'),
    );
    const { result } = renderHook(() => useAssistant(), { wrapper });

    await act(async () => {
      await result.current.send('anything');
    });

    expect(result.current.turns.map((t) => t.role)).toEqual(['user']);
    expect(result.current.isStreaming).toBe(false);
  });

  it('still reports a genuine failure to reach the endpoint', async () => {
    // The exemption must not swallow the case it looks like: a request that
    // never arrived is something the operator needs told about.
    vi.mocked(openAssistantStream).mockRejectedValue(new TypeError('Failed to fetch'));
    const { result } = renderHook(() => useAssistant(), { wrapper });

    await act(async () => {
      await result.current.send('anything');
    });

    const last = result.current.turns.at(-1);
    expect(last?.role).toBe('assistant');
    expect(last?.error).toBeTruthy();
  });
});
