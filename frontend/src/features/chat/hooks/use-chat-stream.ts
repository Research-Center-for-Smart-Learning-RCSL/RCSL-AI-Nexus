'use client';

/**
 * Owns one in-flight generation.
 *
 * The AbortController is the point of this hook. Its signal reaches `fetch`,
 * and it fires on unmount as well as on an explicit cancel, so navigating away
 * mid-generation releases the backend's concurrency slot instead of leaving the
 * runtime producing tokens for nobody (frontend.md section 6).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  createStreamStore,
  type MutableStreamStore,
} from '@/components/composed/stream-message';
import { describeError } from '@/components/composed/error-state';
import { openChatStream } from '@/features/chat/api';
import { readChatStream } from '@/features/chat/stream';
import type { ChatMessage, ChatRequest } from '@/features/chat/schema';

export type ChatTurn = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /** A thinking model's deliberation. Never sent back as history below. */
  reasoning?: string;
  /**
   * The terminal frame's reason, kept so a turn with no answer can say why.
   * `length` is the platform's ceiling, which a thinking model can reach having
   * produced nothing at all.
   */
  finishReason?: string;
  /** How long the generation ran, so the clock survives the live message. */
  elapsedMs?: number;
  /** Set when the turn ended on a terminal error frame. */
  error?: string;
};

/**
 * The messages sent for the next turn.
 *
 * Exported to be tested directly: both rules below are invisible in the UI and
 * only show up in the prompt the model receives, which nothing else inspects.
 *
 * `content` only — a turn's reasoning is deliberately not replayed: it is the
 * model's scratch work, it multiplies the prompt for every later turn, and the
 * ceiling that truncates a generation counts it.
 *
 * Which leaves turns that have no content at all: a thinking model that spent
 * its whole budget deliberating, or a generation that failed before its first
 * token. Those stay in the transcript so the thread shows what happened, but
 * sending one would put `{"role":"assistant","content":""}` into the prompt
 * template, where it becomes an empty assistant turn for this request and every
 * later one. Dropped here rather than at the display layer, because the two
 * want opposite things from the same turn.
 */
export function historyFor(turns: ChatTurn[], prompt: string): ChatMessage[] {
  return [
    ...turns
      .filter((turn) => turn.content)
      .map((turn) => ({ role: turn.role, content: turn.content })),
    { role: 'user' as const, content: prompt },
  ];
}

/**
 * The request body for one turn.
 *
 * Exported for the same reason as `historyFor`: the rule below is invisible in
 * the UI and only shows up in what the server receives.
 *
 * **The toggle's value is always sent, in both directions.** An earlier version
 * omitted the field when thinking was on, reasoning that `true` should not
 * override the deployment default — which had it backwards. With
 * `OLLAMA_THINKING=false` the panel still drew the box checked, the request said
 * nothing, the server applied its `false` default, and the control displayed the
 * opposite of what happened with no way to correct it. A checked box means the
 * caller wants thinking, so it says so.
 *
 * Sending `true` is safe end to end: the adapter maps it to sending no `think`
 * field at all, which is what keeps a non-thinking model from being asked for
 * something it refuses (`ollama_adapter.py`). The value the browser sends and
 * the value that reaches the runtime are deliberately not the same thing.
 */
export function chatRequestFor(
  capability: ChatRequest['capability'],
  messages: ChatMessage[],
  think?: boolean,
  useKnowledge?: boolean,
): ChatRequest {
  return {
    capability,
    messages,
    ...(think === undefined ? {} : { think }),
    // Present only when asked for, unlike `think`, which is sent in both
    // directions because its checkbox would otherwise display the opposite of
    // what happened. Grounding has no such problem: `false` is both the
    // server's default and the absence of the field, so an ordinary turn is
    // exactly the request it was before the knowledge base existed.
    ...(useKnowledge ? { use_knowledge: true } : {}),
  };
}

export function useChatStream() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  const controllerRef = useRef<AbortController | null>(null);
  // The live buffer lives outside React state so a delta re-renders only the
  // active message, not the whole thread.
  const store = useMemo<MutableStreamStore>(() => createStreamStore(), []);

  // Abort on unmount. Without this the request outlives the component.
  useEffect(() => {
    return () => controllerRef.current?.abort();
  }, []);

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  const send = useCallback(
    async (
      capability: ChatRequest['capability'],
      prompt: string,
      think?: boolean,
      useKnowledge = false,
    ) => {
      if (isStreaming) return;

      const history = historyFor(turns, prompt);

      setTurns((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'user', content: prompt },
      ]);

      const controller = new AbortController();
      controllerRef.current = controller;
      // `begin`, not `reset`: the bubble is on screen from here, and the clock
      // it shows has to start now rather than when the first token lands. The
      // gap between the two is what a user reads as the app having hung.
      store.begin();
      setIsStreaming(true);

      let finalError: string | undefined;

      try {
        const response = await openChatStream(
          chatRequestFor(capability, history, think, useKnowledge),
          controller.signal,
        );

        await readChatStream(
          response,
          {
            onDelta: (delta) => store.append(delta),
            onReasoning: (delta) => store.appendReasoning(delta),
            onError: (message) => {
              finalError = message;
              store.fail(message);
            },
            onDone: (finishReason) => store.finish(finishReason),
          },
          controller.signal,
        );
      } catch (caught) {
        // A failure before the first byte still arrives as a normal HTTP error.
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
          finalError = describeError(caught);
          store.fail(finalError);
        }
      } finally {
        const { text: produced, reasoning, finishReason, startedAt } = store.getSnapshot();
        // Whatever was produced is kept. A cancelled or failed generation still
        // shows its partial output, matching how usage is billed server-side.
        // Reasoning alone counts as output: a thinking model that spent its
        // whole budget deliberating produced no answer, and dropping the turn
        // would leave the thread showing nothing at all for it.
        if (produced || reasoning || finalError) {
          setTurns((current) => [
            ...current,
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: produced,
              reasoning: reasoning || undefined,
              finishReason: finishReason ?? undefined,
              elapsedMs: startedAt === null ? undefined : Date.now() - startedAt,
              error: finalError,
            },
          ]);
        }
        store.reset();
        setIsStreaming(false);
        controllerRef.current = null;
      }
    },
    [isStreaming, store, turns],
  );

  const clear = useCallback(() => {
    cancel();
    setTurns([]);
    store.reset();
  }, [cancel, store]);

  return { turns, isStreaming, store, send, cancel, clear };
}
