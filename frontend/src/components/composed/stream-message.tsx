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

import { memo, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
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
  /**
   * When the request was issued, not when the first token arrived. The gap
   * between the two is exactly the interval this component used to render as
   * an empty box, so it is the one the elapsed counter has to measure.
   */
  startedAt: number | null;
  /** Set when a terminal error frame arrived mid-stream. */
  error: string | null;
};

export type StreamStore = {
  subscribe: (onChange: () => void) => () => void;
  getSnapshot: () => StreamSnapshot;
};

export type MutableStreamStore = StreamStore & {
  /**
   * Marks the request as in flight, before any byte has arrived.
   *
   * Without this the status stayed `idle` until the first delta, so the
   * placeholder — which requires `streaming` — was unreachable during the only
   * interval it existed for, and the bubble rendered empty for the whole wait.
   */
  begin: () => void;
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
  startedAt: null,
  error: null,
};

/**
 * A minimal external store. Deliberately not React state: the producer is the
 * stream reader, which lives outside the render cycle and would otherwise
 * schedule a state update per token.
 */
export function createStreamStore(initial = ''): MutableStreamStore {
  let snapshot: StreamSnapshot = initial
    ? { text: initial, reasoning: '', status: 'idle', startedAt: null, error: null }
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
    begin() {
      emit({ ...EMPTY, status: 'streaming', startedAt: Date.now() });
    },
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

/** `2m 14s`, or `14s` under a minute. Seconds only: this is a progress cue. */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  return minutes > 0 ? `${minutes}m ${total % 60}s` : `${total}s`;
}

/**
 * The tail of the reasoning so far, for the one-line ticker.
 *
 * A thinking model emits paragraphs, and the useful signal while it works is
 * *where it currently is*, not everything it has said. Taking the last
 * non-empty line and truncating keeps the summary one line high, which is what
 * lets the block sit still instead of pushing the page down for minutes.
 */
export function reasoningTail(text: string, limit = 70): string {
  const lines = text.split('\n');
  let tail = '';
  for (let i = lines.length - 1; i >= 0 && !tail; i -= 1) tail = lines[i].trim();
  if (!tail) return '';
  return tail.length > limit ? `${tail.slice(-limit)}` : tail;
}

/**
 * Reasoning as a one-line ticker that expands.
 *
 * Collapsed by default and it stays that way unless the reader opens it: an
 * earlier version passed `open` as a controlled prop, so the block snapped shut
 * in the reader's face the moment the first answer token arrived. `defaultOpen`
 * seeds the initial state and nothing overrides it afterwards.
 *
 * The summary carries elapsed time because that is the decision the reader
 * actually has during a long deliberation — this model has been measured
 * producing 23,632 tokens of reasoning and no answer, and the only useful
 * question is whether to stop and re-ask with thinking off. A wall of text
 * answers that worse than a clock does.
 */
export const ReasoningBlock = memo(function ReasoningBlock({
  text,
  defaultOpen = false,
  elapsedMs = null,
}: {
  text: string;
  defaultOpen?: boolean;
  elapsedMs?: number | null;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (!text) return null;

  const tail = reasoningTail(text);
  return (
    <details
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
      className="rounded-md border border-dashed border-foreground/15 px-3 py-2"
    >
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
        <span>Reasoning</span>
        {elapsedMs !== null ? (
          <span className="ml-2 tabular-nums opacity-70">
            {formatElapsed(elapsedMs)}
          </span>
        ) : null}
        {!open && tail ? (
          <span className="ml-2 font-normal italic opacity-70">{tail}</span>
        ) : null}
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
  placeholder = 'Thinking',
}: StreamMessageProps) {
  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    serverSnapshot,
  );

  // A second hand, running only while a request is in flight. The store cannot
  // provide this: nothing arrives from the network during the wait it measures,
  // which is the whole reason the wait used to render as an empty box.
  const [now, setNow] = useState(() => Date.now());
  const running = snapshot.status === 'streaming';
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  const elapsed = snapshot.startedAt === null ? null : now - snapshot.startedAt;
  const waiting = running && !snapshot.reasoning && !snapshot.text;

  return (
    <div data-slot="stream-message" className={cn('space-y-2', className)}>
      <ReasoningBlock text={snapshot.reasoning} elapsedMs={running ? elapsed : null} />

      {snapshot.text ? (
        <SanitisedMarkdown text={snapshot.text} />
      ) : waiting ? (
        // Reached now. This branch required `streaming`, which used to arrive
        // only with the first token, so it never rendered during the wait.
        <p className="text-sm text-muted-foreground">
          {placeholder}
          {elapsed !== null ? (
            <span className="ml-2 tabular-nums opacity-70">
              {formatElapsed(elapsed)}
            </span>
          ) : null}
        </p>
      ) : null}

      {running ? (
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
