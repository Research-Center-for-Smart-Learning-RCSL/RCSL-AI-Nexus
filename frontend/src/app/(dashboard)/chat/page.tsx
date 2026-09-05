import type { Metadata } from 'next';

import { ChatPanel } from '@/features/chat/components/chat-panel';

export const metadata: Metadata = { title: 'Chat' };

export default function ChatPage() {
  return (
    <div className="min-h-0 flex-1">
      <ChatPanel />
    </div>
  );
}
