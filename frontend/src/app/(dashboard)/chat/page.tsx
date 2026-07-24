import type { Metadata } from 'next';

import { ChatPanel } from '@/features/chat/components/chat-panel';

export const metadata: Metadata = { title: 'Chat' };

export default function ChatPage() {
  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Chat</h1>
        <p className="text-sm text-muted-foreground">
          Routed by capability through the admin endpoint, authorised by your
          identity rather than an API key.
        </p>
      </div>
      <div className="min-h-0 flex-1">
        <ChatPanel />
      </div>
    </div>
  );
}
