'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  describeEmptyOutcome,
  ReasoningBlock,
  SanitisedMarkdown,
  StreamMessage,
} from '@/components/composed/stream-message';
import { EmptyState } from '@/components/composed/empty-state';
import { cn } from '@/lib/utils';
import {
  issuableCapabilitySchema,
  type IssuableCapability,
} from '@/features/models/schema';
import { useChatStream } from '@/features/chat/hooks/use-chat-stream';
import type { ChatTurn } from '@/features/chat/hooks/use-chat-stream';

function Turn({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === 'user';
  return (
    <div
      className={cn(
        'rounded-lg px-3 py-2',
        isUser ? 'bg-muted' : 'ring-1 ring-foreground/10',
      )}
    >
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        {isUser ? 'You' : 'Assistant'}
      </p>
      {isUser ? (
        <p className="text-sm whitespace-pre-wrap">{turn.content}</p>
      ) : (
        <div className="space-y-2">
          {/* Open when there is no answer to show: a generation that spent its
              whole budget thinking would otherwise render as an empty bubble.
              The elapsed time comes with it, because the live message that was
              showing it is gone by the time this renders. */}
          <ReasoningBlock
            text={turn.reasoning ?? ''}
            defaultOpen={!turn.content}
            elapsedMs={turn.elapsedMs ?? null}
          />
          {turn.content ? (
            <SanitisedMarkdown text={turn.content} />
          ) : (
            (() => {
              const outcome = describeEmptyOutcome(
                turn.finishReason ?? null,
                turn.elapsedMs ?? null,
              );
              return outcome ? (
                <p className="text-sm text-muted-foreground">{outcome}</p>
              ) : null;
            })()
          )}
        </div>
      )}
      {turn.error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          The response stopped: {turn.error}
        </p>
      ) : null}
    </div>
  );
}

export function ChatPanel() {
  const { turns, isStreaming, store, send, cancel, clear } = useChatStream();
  const [capability, setCapability] = useState<IssuableCapability>('chat');
  // Both positions are sent explicitly, so the box always describes what the
  // request asked for rather than what a server-side default happens to be.
  // Turning it off is the lever for a question a thinking model will not stop
  // reasoning about: measured, the same prompt answered in 49 seconds with
  // thinking off after producing nothing in 23,632 tokens with it on.
  const [thinking, setThinking] = useState(true);
  const [prompt, setPrompt] = useState('');
  // Off by default, matching the API: grounding costs an embedding call and a
  // slice of the context window, so it is asked for rather than assumed.
  const [useKnowledge, setUseKnowledge] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [turns.length, isStreaming]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed || isStreaming) return;
    setPrompt('');
    void send(capability, trimmed, thinking, useKnowledge);
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex-1 space-y-3 overflow-y-auto">
        {turns.length === 0 && !isStreaming ? (
          <EmptyState
            title="No messages yet"
            description="This talks to the admin chat endpoint, which authorises by your identity rather than an API key. The same resource guardrails apply."
          />
        ) : null}

        {turns.map((turn) => (
          <Turn key={turn.id} turn={turn} />
        ))}

        {isStreaming ? (
          <div className="rounded-lg px-3 py-2 ring-1 ring-foreground/10">
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Assistant
            </p>
            <StreamMessage store={store} />
          </div>
        ) : null}

        <div ref={bottomRef} />
      </div>

      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          className="size-4 accent-primary"
          checked={useKnowledge}
          onChange={(event) => setUseKnowledge(event.target.checked)}
        />
        Answer from the knowledge base
      </label>

      <form onSubmit={submit} className="flex items-center gap-2">
        <Select
          value={capability}
          onValueChange={(value) => setCapability(value as IssuableCapability)}
        >
          <SelectTrigger className="w-36" aria-label="Capability">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {issuableCapabilitySchema.options.map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <label className="flex shrink-0 items-center gap-1.5 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={thinking}
            disabled={isStreaming}
            onChange={(event) => setThinking(event.target.checked)}
          />
          Thinking
        </label>

        <Input
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Ask something"
          disabled={isStreaming}
          className="flex-1"
          aria-label="Message"
        />

        {isStreaming ? (
          <Button type="button" variant="outline" onClick={cancel}>
            Stop
          </Button>
        ) : (
          <Button type="submit" disabled={!prompt.trim()}>
            Send
          </Button>
        )}

        <Button
          type="button"
          variant="ghost"
          onClick={clear}
          disabled={turns.length === 0 && !isStreaming}
        >
          Clear
        </Button>
      </form>
    </div>
  );
}
