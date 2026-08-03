import type { Metadata } from 'next';

import { ChatPanel } from '@/features/chat/components/chat-panel';

export const metadata: Metadata = { title: 'Chat' };

export default function ChatPage() {
  return (
    // Fills whatever the shell has left rather than measuring the viewport and
    // subtracting a guess. The old `calc(100vh-8rem)` did not know about the
    // session-expiry banner, so the composer slid below the fold for the last
    // five minutes of every session — exactly when someone is most likely to be
    // mid-sentence.
    <div className="flex min-h-0 flex-1 flex-col gap-4">
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
