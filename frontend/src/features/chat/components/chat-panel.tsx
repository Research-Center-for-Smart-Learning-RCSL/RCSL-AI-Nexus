'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';

import { EmptyState } from '@/components/composed/empty-state';
import { StreamMessage } from '@/components/composed/stream-message';
import { useChatStream } from '@/features/chat/hooks/use-chat-stream';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';
import type { IssuableCapability } from '@/features/models/schema';

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
      <div className="flex-1 space-y-3 overflow-y-auto overscroll-contain">
        {turns.length === 0 && !isStreaming ? (
          <EmptyState
            title="No messages yet"
            description="This screen calls the admin chat endpoint, which authorises by the signed-in identity rather than an API key. The same resource guardrails apply."
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
        <div ref={bottomRef} />
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
