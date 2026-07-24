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
  /** Set when the turn ended on a terminal error frame. */
  error?: string;
};

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
    async (capability: ChatRequest['capability'], prompt: string) => {
      if (isStreaming) return;

      const history: ChatMessage[] = [
        ...turns.map((turn) => ({ role: turn.role, content: turn.content })),
        { role: 'user' as const, content: prompt },
      ];

      setTurns((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'user', content: prompt },
      ]);

      const controller = new AbortController();
      controllerRef.current = controller;
      store.reset();
      setIsStreaming(true);

      let finalError: string | undefined;

      try {
        const response = await openChatStream(
          { capability, messages: history },
          controller.signal,
        );

        await readChatStream(
          response,
          {
            onDelta: (delta) => store.append(delta),
            onError: (message) => {
              finalError = message;
              store.fail(message);
            },
            onDone: () => store.finish(),
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
        const produced = store.getSnapshot().text;
        // Whatever was produced is kept. A cancelled or failed generation still
        // shows its partial output, matching how usage is billed server-side.
        if (produced || finalError) {
          setTurns((current) => [
            ...current,
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: produced,
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
