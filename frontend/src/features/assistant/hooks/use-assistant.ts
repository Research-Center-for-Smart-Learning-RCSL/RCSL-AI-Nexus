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
import { z } from 'zod';

import { createStreamStore } from '@/components/composed/stream-message';
import { describeError } from '@/components/composed/error-state';
import { openAssistantStream } from '@/features/assistant/api';
import {
  assistRoleSchema,
  proposalSchema,
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
 * What a restored turn has to satisfy to be replayed or rendered.
 *
 * Parsed rather than shape-checked, and every field rather than two. The stored
 * value is whatever this tab wrote under some earlier build, so a turn can
 * arrive carrying a `proposal` from a schema that has since changed — and
 * `ProposalCard` reads `Object.entries(proposal.fields)`, which throws during
 * render on a proposal missing `fields`. That is an exception inside the app
 * shell with no error boundary above it: the whole dashboard fails to load,
 * which is exactly the failure the loader exists to prevent. A bad `role` is
 * the milder version — it replays into the request and 422s.
 */
const storedTurnSchema = z.object({
  id: z.string(),
  role: assistRoleSchema,
  content: z.string(),
  proposal: proposalSchema.optional(),
  finishReason: z.string().optional(),
  error: z.string().optional(),
});

/**
 * Loaded defensively. A drawer that throws on mount takes the shell down with
 * it, so an unreadable entry is dropped rather than repaired.
 *
 * Exported to be tested directly, like `historyFor`: what it guards against is
 * a value written by a build that no longer exists, which no test can produce
 * by driving the hook normally.
 */
export function loadTurns(): AssistantTurn[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((turn) => {
      const result = storedTurnSchema.safeParse(turn);
      return result.success ? [result.data] : [];
    });
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
      // Room for the question, which is appended below and counts against the
      // same cap. Slicing to the full `MAX_TURNS` and then appending sent 41
      // messages to a schema that accepts 40, so after twenty exchanges every
      // further question was refused — permanently, since the transcript is
      // restored from `sessionStorage` on the next load, and only the Clear
      // button could recover it.
      .slice(-(MAX_TURNS - 1))
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
  // Bumped by `clear`, and compared in the `finally` below. Clearing while an
  // answer is streaming otherwise emptied the transcript and then let the
  // in-flight request append its turn into the empty list, leaving one orphaned
  // bubble — and writing it to `sessionStorage`. The Clear button is
  // deliberately enabled mid-stream, so this is the ordinary path, not a race.
  const generation = useRef(0);

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
      const mine = ++generation.current;

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
        // Pressing Stop before the response headers arrive rejects the fetch
        // rather than ending the read, and a cancellation is a user action, not
        // a failure. Reported as one it read "The answer stopped: signal is
        // aborted without reason", which describes the implementation rather
        // than anything the operator did.
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
          failure = describeError(caught);
          store.fail(failure);
        }
      } finally {
        // Nothing to show is nothing to record: cancelling before the first
        // token would otherwise leave an empty Assistant bubble in the
        // transcript, and in `sessionStorage`.
        //
        // **`proposal` counts as something to show.** A model that puts its
        // whole answer into the proposal and writes no prose produced a turn
        // with an empty `answer`, which this dropped silently — the operator's
        // own question appeared and nothing ever followed it, with no error
        // anywhere. Reproduced 2026-08-07 on a two-turn conversation where the
        // second reply was a proposal and nothing else.
        if (generation.current === mine && (answer || failure || proposal)) {
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
        }
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
    // Retires whatever is in flight, so its `finally` does not append into the
    // transcript this is emptying.
    generation.current += 1;
    setTurns([]);
    store.reset();
  }, [store]);

  return { turns, isStreaming, store, send, cancel, clear };
}
