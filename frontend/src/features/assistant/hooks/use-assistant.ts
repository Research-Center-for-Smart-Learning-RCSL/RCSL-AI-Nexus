'use client';

/**
 * One assistant conversation, for as long as the tab is open.
 *
 * Two things differ from `useChatStream`, and both follow from this being a
 * drawer rather than a page.
 *
 * **It survives navigation.** The drawer is mounted by the app shell, so it
 * outlives every route change, and the transcript is written to
 * `sessionStorage` so it also outlives a reload. Not to the server: a
 * conversation about which key to revoke has no reason to become a row anybody
 * has to classify, retain and eventually explain. Closing the tab is the
 * deletion policy, and it needs no code.
 *
 * **It reads a trailer.** The proposal arrives after the terminal frame, so the
 * reader is told to keep going to `[DONE]` — see `onTrailer` in
 * `features/chat/stream.ts`. Only the newest proposal is kept: an older card
 * describes a form state that has since moved on, and offering two is offering
 * a choice nobody asked for.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { createStreamStore } from '@/components/composed/stream-message';
import { describeError } from '@/components/composed/error-state';
import { openAssistantStream } from '@/features/assistant/api';
import {
  readProposalFrame,
  type AssistMessage,
  type Proposal,
} from '@/features/assistant/schema';
import { useAssistantContext } from '@/features/assistant/context';
import { readChatStream } from '@/features/chat/stream';

export type AssistantTurn = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /** The proposal that arrived with this turn, if any. */
  proposal?: Proposal;
  finishReason?: string;
  error?: string;
};

const STORAGE_KEY = 'nexus:assistant:transcript';
const MAX_TURNS = 40;

/**
 * Loaded defensively. The value is whatever was in storage when this tab last
 * ran, which may be from an older build with a different shape, and a drawer
 * that throws on mount takes the whole shell down with it.
 */
function loadTurns(): AssistantTurn[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (turn): turn is AssistantTurn =>
        typeof turn === 'object' &&
        turn !== null &&
        typeof (turn as AssistantTurn).id === 'string' &&
        typeof (turn as AssistantTurn).content === 'string',
    );
  } catch {
    return [];
  }
}

/**
 * What is sent as history: content only, and only turns that have some.
 *
 * The same rule `historyFor` applies in the chat panel, for the same reason —
 * an empty assistant turn would become `{"role":"assistant","content":""}` in
 * the prompt for this request and every later one. Proposals are not replayed
 * either: they are already described by the prose that accompanied them, and
 * sending the JSON back would invite the model to treat its own output as a
 * settled decision.
 */
export function historyFor(
  turns: AssistantTurn[],
  question: string,
): AssistMessage[] {
  return [
    ...turns
      .filter((turn) => turn.content)
      .slice(-MAX_TURNS)
      .map((turn) => ({ role: turn.role, content: turn.content })),
    { role: 'user' as const, content: question },
  ];
}

export function useAssistant() {
  const context = useAssistantContext();
  const [turns, setTurns] = useState<AssistantTurn[]>(loadTurns);
  const [isStreaming, setIsStreaming] = useState(false);
  const store = useMemo(() => createStreamStore(), []);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(turns));
    } catch {
      // A full or disabled store is not a reason to lose the conversation
      // that is on screen. It just will not survive a reload.
    }
  }, [turns]);

  // The drawer is mounted by the app shell and unmounts only when the tab
  // closes, so this fires far less often than the chat panel's equivalent —
  // which is exactly why it matters that it exists at all.
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

      // Read at send time rather than subscribed to, so a keystroke does not
      // re-render the drawer mid-stream. See `features/assistant/context.tsx`.
      const draft = context.readDraft();

      let proposal: Proposal | null = null;
      let answer = '';
      let failure: string | undefined;
      let finishReason: string | undefined;

      try {
        const response = await openAssistantStream(
          {
            surface: context.surface,
            messages: history,
            draft,
            key_id: context.keyId,
          },
          abort.signal,
        );

        await readChatStream(
          response,
          {
            onDelta: (text) => {
              answer += text;
              store.append(text);
            },
            onError: (message) => {
              failure = message;
              store.fail(message);
            },
            onDone: (reason) => {
              finishReason = reason ?? undefined;
              store.finish(reason);
            },
            // Offered every frame the reader has no interpretation for, and
            // validated here. The last one wins.
            onTrailer: (raw) => {
              const found = readProposalFrame(raw);
              if (found) proposal = found;
            },
          },
          abort.signal,
        );
      } catch (caught) {
        failure = describeError(caught);
        store.fail(failure);
      } finally {
        setTurns((previous) => [
          ...previous,
          {
            id: `a-${Date.now()}`,
            role: 'assistant',
            content: answer,
            proposal: proposal ?? undefined,
            finishReason,
            error: failure,
          },
        ]);
        setIsStreaming(false);
        store.reset();
        controller.current = null;
      }
    },
    [context, isStreaming, store, turns],
  );

  const cancel = useCallback(() => controller.current?.abort(), []);

  const clear = useCallback(() => {
    controller.current?.abort();
    setTurns([]);
    store.reset();
  }, [store]);

  return { turns, isStreaming, store, send, cancel, clear };
}
