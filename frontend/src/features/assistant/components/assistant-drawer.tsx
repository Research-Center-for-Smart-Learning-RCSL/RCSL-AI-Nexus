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
import { XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  SanitisedMarkdown,
  StreamMessage,
} from '@/components/composed/stream-message';
import { cn } from '@/lib/utils';
import { useAssistantContext } from '@/features/assistant/context';
import { useAssistant, type AssistantTurn } from '@/features/assistant/hooks/use-assistant';
import {
  ProposalCard,
  proposalToFormPatch,
} from '@/features/assistant/components/proposal-card';
import type { Proposal } from '@/features/assistant/schema';

const SURFACE_LABELS: Record<string, string> = {
  'api_keys.create': 'Issuing a key',
  'api_keys.edit': 'Editing a key',
  'api_keys.list': 'Your API keys',
  api_docs: 'Integration',
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
      className="bg-background fixed inset-y-0 right-0 z-40 flex w-full max-w-sm flex-col border-l shadow-lg"
    >
      <header className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <div className="min-w-0">
          <p className="font-heading text-sm font-semibold">Assistant</p>
          <p className="truncate text-xs text-muted-foreground">
            {SURFACE_LABELS[context.surface] ?? SURFACE_LABELS.other}
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setOpen(false)}
          aria-label="Close the assistant"
        >
          <XIcon className="size-4" />
        </Button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {turns.length === 0 && !isStreaming ? (
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>
              Ask about this deployment&apos;s settings. On a key form it can
              suggest values, which you then apply and save yourself.
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
