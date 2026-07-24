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
  fail: (message: string) => void;
  finish: () => void;
  reset: () => void;
};

const EMPTY: StreamSnapshot = { text: '', status: 'idle', error: null };

/**
 * A minimal external store. Deliberately not React state: the producer is the
 * stream reader, which lives outside the render cycle and would otherwise
 * schedule a state update per token.
 */
export function createStreamStore(initial = ''): MutableStreamStore {
  let snapshot: StreamSnapshot = initial
    ? { text: initial, status: 'idle', error: null }
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
      emit({ text: snapshot.text + delta, status: 'streaming', error: null });
    },
    fail(message) {
      // Keeps whatever was produced. Truncated output with a visible reason is
      // strictly better than a blank bubble.
      emit({ text: snapshot.text, status: 'error', error: message });
    },
    finish() {
      if (snapshot.status === 'error') return;
      emit({ text: snapshot.text, status: 'done', error: null });
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
      {snapshot.text ? (
        <SanitisedMarkdown text={snapshot.text} />
      ) : snapshot.status === 'streaming' ? (
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
