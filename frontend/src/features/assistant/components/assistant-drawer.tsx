'use client';

/**
 * The assistant, as a panel that slides in beside whatever the operator is
 * doing.
 *
 * Mounted once by the app shell rather than per page, which is what lets a
 * conversation survive navigating from the key list to the API documentation
 * and back — the exact journey the questions tend to follow.
 *
 * Available to every role. API keys and the integration documentation are
 * member-reachable (security.md §5.2 grants a member their own keys), and a
 * member holds `chat:use`, which is the scope the endpoint requires. Gating
 * this to administrators would withhold the help from the people most likely
 * to need it.
 */

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ChevronsLeftIcon, ChevronsRightIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  SanitisedMarkdown,
  StreamMessage,
} from '@/components/composed/stream-message';
import { cn } from '@/lib/utils';
import { useAssistantContext } from '@/features/assistant/context';
import {
  readWidePreference,
  WIDTH_EVENT,
  WIDTH_KEY,
} from '@/features/assistant/width';
import { useAssistant, type AssistantTurn } from '@/features/assistant/hooks/use-assistant';
import {
  ProposalCard,
  proposalToFormPatch,
} from '@/features/assistant/components/proposal-card';
import type { Proposal } from '@/features/assistant/schema';

const SURFACE_LABELS: Record<string, string> = {
  'api_keys.create': 'Issuing a key',
  'api_keys.edit': 'Editing a key',
  'api_keys.list': 'The key list',
  api_docs: 'Integration',
  agent_setup: 'Connecting an agent',
  other: 'This platform',
};

function Turn({
  turn,
  canApply,
  onApply,
}: {
  turn: AssistantTurn;
  canApply: boolean;
  onApply: (proposal: Proposal) => void;
}) {
  const isUser = turn.role === 'user';
  return (
    <div
      className={cn(
        'rounded-lg px-3 py-2 text-sm',
        isUser ? 'bg-muted' : 'ring-1 ring-foreground/10',
      )}
    >
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        {isUser ? 'You' : 'Assistant'}
      </p>
      {isUser ? (
        <p className="whitespace-pre-wrap">{turn.content}</p>
      ) : (
        <SanitisedMarkdown text={turn.content} />
      )}
      {turn.proposal ? (
        <ProposalCard
          proposal={turn.proposal}
          canApply={canApply}
          onApply={onApply}
        />
      ) : null}
      {turn.error ? (
        <p role="alert" className="mt-2 text-destructive">
          The answer stopped: {turn.error}
        </p>
      ) : null}
    </div>
  );
}

export function AssistantDrawer() {
  const [question, setQuestion] = useState('');
  const context = useAssistantContext();
  const { isOpen: open, setOpen } = context;
  const { turns, isStreaming, store, send, cancel, clear } = useAssistant();
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [open, turns.length, isStreaming]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isStreaming) return;
    setQuestion('');
    void send(trimmed);
  }

  // Persisted, because the reason to widen it — reading a long answer beside a
  // form — does not go away when the panel closes. `localStorage` rather than a
  // server preference: it is a property of this screen on this machine, and a
  // round trip to store it would be the heaviest thing this component does.
  const [wide, setWide] = useState(false);

  useEffect(() => {
    setWide(readWidePreference());
  }, []);

  function toggleWidth() {
    setWide((previous) => {
      const next = !previous;
      window.localStorage.setItem(WIDTH_KEY, next ? 'wide' : 'narrow');
      // The shell reserves the matching padding, and it cannot read this
      // component's state. An event is the smallest thing that keeps the two in
      // step without lifting the state into a context every screen would carry.
      window.dispatchEvent(new CustomEvent(WIDTH_EVENT, { detail: next }));
      return next;
    });
  }

  function apply(proposal: Proposal) {
    context.applyPatch(proposalToFormPatch(proposal.fields));
  }

  // Nothing to render when closed: the button that opens it lives in the shell
  // header. It used to float at the bottom-right corner, which is exactly where
  // the chat composer puts its own Stop and Clear buttons, so on the one screen
  // where both are in reach they sat on top of each other.
  if (!open) return null;

  return (
    <aside
      // Not a modal. The operator is meant to read the answer and type into the
      // form at the same time, and a dialog that traps focus would make the one
      // workflow this exists for impossible.
      //
      // On a wide screen the shell reserves the same width as padding, so the
      // panel sits beside the content rather than over it. Narrower than that
      // there is no room to reserve and it does cover the page, which is why the
      // header button stays visible underneath to close it again.
      aria-label="Management assistant"
      className={cn(
        'bg-background fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l shadow-lg',
        // Two widths rather than a drag handle. The need is "this is too narrow
        // to read", which a second size answers; a handle would add pointer
        // capture, touch targets and a keyboard story for a preference with two
        // useful values.
        wide ? 'max-w-2xl' : 'max-w-sm',
      )}
    >
      <header className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <div className="min-w-0">
          <p className="font-heading text-sm font-semibold">Assistant</p>
          <p className="truncate text-xs text-muted-foreground">
            {SURFACE_LABELS[context.surface] ?? SURFACE_LABELS.other}
          </p>
        </div>
        <div className="flex shrink-0 items-center">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            // Hidden below `sm`, where the panel already fills the screen and
            // widening it would do nothing.
            className="hidden sm:inline-flex"
            onClick={toggleWidth}
            aria-label={wide ? 'Narrow the assistant' : 'Widen the assistant'}
            aria-pressed={wide}
          >
            {wide ? (
              <ChevronsRightIcon className="size-4" />
            ) : (
              <ChevronsLeftIcon className="size-4" />
            )}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setOpen(false)}
            aria-label="Close the assistant"
          >
            <XIcon className="size-4" />
          </Button>
        </div>
      </header>

      <div
        // `overscroll-contain`: this panel is `fixed`, so when its scroll
        // reached the end the browser chained the gesture to the document
        // behind it — the page drifted while the panel stayed put, which reads
        // as the panel being broken. Contained, the gesture stops at the edge.
        className="flex-1 space-y-3 overflow-y-auto overscroll-contain px-4 py-3"
      >
        {turns.length === 0 && !isStreaming ? (
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>
              Ask about this deployment&apos;s settings. On a key form it can
              suggest values; applying and saving them stays a manual step.
            </p>
            <p>
              It advises only. It cannot issue, edit or revoke anything, and it
              cannot see any key&apos;s secret.
            </p>
          </div>
        ) : null}

        {turns.map((turn) => (
          <Turn
            key={turn.id}
            turn={turn}
            canApply={context.canApply}
            onApply={apply}
          />
        ))}

        {isStreaming ? (
          <div
            className="rounded-lg px-3 py-2 text-sm ring-1 ring-foreground/10"
            aria-busy="true"
          >
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Assistant
            </p>
            <StreamMessage store={store} />
          </div>
        ) : null}

        {/* State only, for the same reason as the chat panel: announcing the
            body would repeat the whole answer once per token. */}
        <p aria-live="polite" className="sr-only">
          {isStreaming
            ? 'Answering.'
            : turns.length > 0
              ? 'Answer complete.'
              : ''}
        </p>

        <div ref={bottomRef} />
      </div>

      <form onSubmit={submit} className="flex items-center gap-2 border-t px-4 py-3">
        <Input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about this screen"
          disabled={isStreaming}
          className="flex-1"
          aria-label="Ask the assistant"
        />
        {isStreaming ? (
          <Button type="button" variant="outline" size="sm" onClick={cancel}>
            Stop
          </Button>
        ) : (
          <Button type="submit" size="sm" disabled={!question.trim()}>
            Ask
          </Button>
        )}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={clear}
          disabled={turns.length === 0 && !isStreaming}
        >
          Clear
        </Button>
      </form>
    </aside>
  );
}
