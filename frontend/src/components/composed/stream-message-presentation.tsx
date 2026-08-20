'use client';

import { useEffect, useState, useSyncExternalStore } from 'react';

import { cn } from '@/lib/utils';

import { ReasoningBlock, formatElapsed } from './reasoning-block';
import { SanitisedMarkdown } from './sanitised-markdown';
import { describeEmptyOutcome } from './stream-message-outcome';
import { serverSnapshot, type StreamStore } from './stream-message-store';

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
  const emptyOutcome = snapshot.text
    ? null
    : describeEmptyOutcome(snapshot.finishReason, elapsed);

  return (
    <div data-slot="stream-message" className={cn('space-y-2', className)}>
      <ReasoningBlock text={snapshot.reasoning} elapsedMs={elapsed} />

      {snapshot.text ? (
        <SanitisedMarkdown text={snapshot.text} />
      ) : emptyOutcome ? (
        <p className="text-sm text-muted-foreground">{emptyOutcome}</p>
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
