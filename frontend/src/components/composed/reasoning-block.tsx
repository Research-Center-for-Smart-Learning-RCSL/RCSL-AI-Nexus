'use client';

import { memo, useState } from 'react';

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
