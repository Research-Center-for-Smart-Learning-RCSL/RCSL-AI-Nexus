'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { createStreamStore } from '@/components/composed/stream-message';
import { useAssistantContext } from '@/features/assistant/context';

import { historyFor } from './assistant-history';
import { runAssistantRequest } from './assistant-request';
import {
  loadTurns,
  persistTurns,
  type AssistantTurn,
} from './assistant-transcript';

export type { AssistantTurn } from './assistant-transcript';
export { historyFor } from './assistant-history';
export { loadTurns } from './assistant-transcript';

export function useAssistant() {
  const context = useAssistantContext();
  const [turns, setTurns] = useState<AssistantTurn[]>(loadTurns);
  const [isStreaming, setIsStreaming] = useState(false);
  const store = useMemo(() => createStreamStore(), []);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);

  useEffect(() => persistTurns(turns), [turns]);
  useEffect(() => () => controller.current?.abort(), []);

  const send = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || isStreaming) return;

      const asked: AssistantTurn = {
        id: `u-${Date.now()}`,
        role: 'user',
        content: trimmed,
      };
      const history = historyFor(turns, trimmed);
      setTurns((previous) => [...previous, asked]);
      setIsStreaming(true);
      store.reset();
      store.begin();

      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      const mine = ++generation.current;

      const result = await runAssistantRequest({
        surface: context.surface,
        messages: history,
        draft: context.readDraft(),
        keyId: context.keyId,
        signal: abort.signal,
        store,
      });

      if (
        generation.current === mine &&
        (result.answer || result.failure || result.proposal)
      ) {
        setTurns((previous) => [
          ...previous,
          {
            id: `a-${Date.now()}`,
            role: 'assistant',
            content: result.answer,
            proposal: result.proposal ?? undefined,
            finishReason: result.finishReason,
            error: result.failure,
          },
        ]);
      }
      setIsStreaming(false);
      store.reset();
      controller.current = null;
    },
    [context, isStreaming, store, turns],
  );

  const cancel = useCallback(() => controller.current?.abort(), []);
  const clear = useCallback(() => {
    controller.current?.abort();
    generation.current += 1;
    setTurns([]);
    store.reset();
  }, [store]);

  return { turns, isStreaming, store, send, cancel, clear };
}
