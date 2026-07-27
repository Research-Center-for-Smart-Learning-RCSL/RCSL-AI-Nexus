'use client';

/**
 * Incremental assistant output. See frontend.md sections 6 and 8.
 *
 * Two things are structural rather than stylistic:
 *
 *  - The accumulating buffer lives in an external store that only this
 *    component subscribes to, so a delta re-renders the active message and
 *    nothing else in the thread.
 *  - Markdown is sanitised over the *accumulated* buffer on each render, never
 *    per delta. Sanitising partial markdown and concatenating the results can
 *    produce different output than sanitising the finished document, which is
 *    exactly the gap an injection would aim at. Raw HTML passthrough stays off:
 *    `rehype-raw` is deliberately absent.
 */

import { memo, useMemo, useSyncExternalStore } from 'react';
import Markdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';

import { cn } from '@/lib/utils';

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

export type StreamSnapshot = {
  /** Everything received so far, concatenated. */
  text: string;
  /**
   * A thinking model's deliberation, accumulated separately from `text`. Kept
   * apart all the way to the render so it can never be mistaken for the answer.
   */
  reasoning: string;
  status: StreamStatus;
  /** Set when a terminal error frame arrived mid-stream. */
  error: string | null;
};

export type StreamStore = {
  subscribe: (onChange: () => void) => () => void;
  getSnapshot: () => StreamSnapshot;
};

export type MutableStreamStore = StreamStore & {
  append: (delta: string) => void;
  appendReasoning: (delta: string) => void;
  fail: (message: string) => void;
  finish: () => void;
  reset: () => void;
};

const EMPTY: StreamSnapshot = {
  text: '',
  reasoning: '',
  status: 'idle',
  error: null,
};

/**
 * A minimal external store. Deliberately not React state: the producer is the
 * stream reader, which lives outside the render cycle and would otherwise
 * schedule a state update per token.
 */
export function createStreamStore(initial = ''): MutableStreamStore {
  let snapshot: StreamSnapshot = initial
    ? { text: initial, reasoning: '', status: 'idle', error: null }
    : EMPTY;
  const listeners = new Set<() => void>();

  function emit(next: StreamSnapshot) {
    snapshot = next;
    for (const listener of listeners) listener();
  }

  return {
    subscribe(onChange) {
      listeners.add(onChange);
      return () => listeners.delete(onChange);
    },
    getSnapshot: () => snapshot,
    append(delta) {
      if (!delta) return;
      emit({ ...snapshot, text: snapshot.text + delta, status: 'streaming', error: null });
    },
    appendReasoning(delta) {
      if (!delta) return;
      // Sets `streaming` exactly as `append` does. For a thinking model this is
      // the only signal there is for as long as it deliberates, and a status
      // that stayed `idle` through it would render as a stalled request.
      emit({
        ...snapshot,
        reasoning: snapshot.reasoning + delta,
        status: 'streaming',
        error: null,
      });
    },
    fail(message) {
      // Keeps whatever was produced. Truncated output with a visible reason is
      // strictly better than a blank bubble.
      emit({ ...snapshot, status: 'error', error: message });
    },
    finish() {
      if (snapshot.status === 'error') return;
      emit({ ...snapshot, status: 'done', error: null });
    },
    reset() {
      emit(EMPTY);
    },
  };
}

/** Server snapshot: streaming never happens during SSR. */
function serverSnapshot(): StreamSnapshot {
  return EMPTY;
}

export const SanitisedMarkdown = memo(function SanitisedMarkdown({
  text,
}: {
  text: string;
}) {
  const plugins = useMemo(() => [rehypeSanitize], []);
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert [&_pre]:overflow-x-auto">
      <Markdown rehypePlugins={plugins}>{text}</Markdown>
    </div>
  );
});

/**
 * Reasoning, collapsed by default.
 *
 * Open while it is the only thing arriving, so a thinking model shows progress
 * rather than a spinner, and closed once the answer starts: by then the answer
 * is what the reader wants and the deliberation is reference material. `open`
 * is passed rather than held as state so both callers stay stateless.
 */
export const ReasoningBlock = memo(function ReasoningBlock({
  text,
  open = false,
}: {
  text: string;
  open?: boolean;
}) {
  if (!text) return null;
  return (
    <details
      open={open}
      className="rounded-md border border-dashed border-foreground/15 px-3 py-2"
    >
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
        Reasoning
      </summary>
      <p className="mt-2 text-xs whitespace-pre-wrap text-muted-foreground">
        {text}
      </p>
    </details>
  );
});

export type StreamMessageProps = {
  store: StreamStore;
  className?: string;
  /** Shown while the buffer is still empty. */
  placeholder?: string;
};

export function StreamMessage({
  store,
  className,
  placeholder = 'Thinking...',
}: StreamMessageProps) {
  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    serverSnapshot,
  );

  return (
    <div data-slot="stream-message" className={cn('space-y-2', className)}>
      <ReasoningBlock text={snapshot.reasoning} open={!snapshot.text} />

      {snapshot.text ? (
        <SanitisedMarkdown text={snapshot.text} />
      ) : snapshot.status === 'streaming' && !snapshot.reasoning ? (
        <p className="text-sm text-muted-foreground">{placeholder}</p>
      ) : null}

      {snapshot.status === 'streaming' ? (
        <span
          aria-hidden
          className="inline-block h-4 w-1.5 animate-pulse bg-foreground/60 align-text-bottom"
        />
      ) : null}

      {snapshot.error ? (
        <p role="alert" className="text-sm text-destructive">
          The response stopped: {snapshot.error}
        </p>
      ) : null}
    </div>
  );
}
