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
        <p className="max-w-prose text-sm text-muted-foreground">
          Ask this deployment&apos;s models a question directly, signed in as
          yourself — no API key is involved, and nothing here is reachable from
          outside. Choose a <strong>capability</strong> rather than a model: the
          name describes the job, and the platform decides which model serves
          it, so conversations keep working when the models behind a name are
          replaced.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Replies stream as they are produced, and <strong>Stop</strong> ends a
          reply that is going nowhere — it stops the work on the server rather
          than only hiding it.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Two things change what a model is working from. A{' '}
          <strong>prompt template</strong> applies saved standing instructions
          to the conversation, and is chosen per conversation rather than set
          once. <strong>Retrieval</strong> has answers drawn from your
          tenant&apos;s uploaded documents; it is off unless switched on, so by
          default a reply comes from the model alone.
        </p>
      </div>
      <div className="min-h-0 flex-1">
        <ChatPanel />
      </div>
    </div>
  );
}
