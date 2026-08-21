'use client';

import { useState, type FormEvent } from 'react';
import { ArrowDownIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/composed/empty-state';
import { StreamMessage } from '@/components/composed/stream-message';
import { useChatStream } from '@/features/chat/hooks/use-chat-stream';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';
import type { IssuableCapability } from '@/features/models/schema';
import { useStickToBottom } from '@/lib/use-stick-to-bottom';

import { ChatComposer } from './chat-composer';
import { ChatTurn } from './chat-turn';

export function ChatPanel() {
  const { turns, isStreaming, store, send, cancel, clear } = useChatStream();
  const { data: gateway, isLoading: gatewayLoading } = useGatewayInfo();
  const servable = new Set(gateway?.capabilities ?? []);
  const [capability, setCapability] = useState<IssuableCapability>('chat');
  const [thinking, setThinking] = useState(true);
  const [prompt, setPrompt] = useState('');
  const [useKnowledge, setUseKnowledge] = useState(false);

  // Following the reply as it is written, rather than jumping once per message.
  // Tokens arrive on the stream store, which by design does not re-render this
  // component, so the previous effect — keyed on the turn count — fired when a
  // reply began and never again while it was produced. A long answer scrolled
  // itself out of view and stayed there until it finished.
  const { containerRef, contentRef, onScroll, pinned, scrollToBottom } =
    useStickToBottom();

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed || isStreaming) return;
    setPrompt('');
    // The reader's own message is the one moment following is unconditional:
    // they have just acted, and the result of that action is at the bottom.
    scrollToBottom();
    void send(capability, trimmed, thinking, useKnowledge);
  }

  const hasContent = turns.length > 0 || isStreaming;

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="relative min-h-0 flex-1">
        <div
          ref={containerRef}
          onScroll={onScroll}
          className="h-full overflow-y-auto overscroll-contain"
        >
          <div ref={contentRef} className="space-y-3">
            {turns.length === 0 && !isStreaming ? (
              <EmptyState
                title="No messages"
                description="This screen is authorised by the signed-in identity rather than by an API key. The same resource limits apply."
              />
            ) : null}
            {turns.map((turn) => (
              <ChatTurn key={turn.id} turn={turn} />
            ))}
            {isStreaming ? (
              <div
                className="rounded-lg px-3 py-2 ring-1 ring-foreground/10"
                aria-busy="true"
              >
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  Assistant
                </p>
                <StreamMessage store={store} />
              </div>
            ) : null}
            <p aria-live="polite" className="sr-only">
              {isStreaming
                ? 'Generating a reply.'
                : turns.length > 0
                  ? 'Reply complete.'
                  : ''}
            </p>
          </div>
        </div>

        {/* Offered only once the reader has scrolled away, because that is the
            only state in which the end of the transcript is somewhere they
            cannot see. */}
        {!pinned && hasContent ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center">
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="pointer-events-auto bg-background shadow-md"
              onClick={() => scrollToBottom('smooth')}
            >
              <ArrowDownIcon className="size-4" />
              Jump to latest
            </Button>
          </div>
        ) : null}
      </div>

      <ChatComposer
        capability={capability}
        setCapability={setCapability}
        thinking={thinking}
        setThinking={setThinking}
        prompt={prompt}
        setPrompt={setPrompt}
        useKnowledge={useKnowledge}
        setUseKnowledge={setUseKnowledge}
        isStreaming={isStreaming}
        hasTurns={turns.length > 0}
        gatewayLoading={gatewayLoading}
        servable={servable}
        onSubmit={submit}
        onCancel={cancel}
        onClear={clear}
      />
    </div>
  );
}
