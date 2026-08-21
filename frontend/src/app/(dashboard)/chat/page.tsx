import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { ChatPanel } from '@/features/chat/components/chat-panel';

export const metadata: Metadata = { title: 'Chat' };

export default function ChatPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <PageHeader
        lead={
          <>
            Direct access to this deployment&apos;s models, authorised by the
            signed-in identity rather than by an API key.{' '}
            <strong>
              A model will answer a question its material cannot determine, so
              verify an answer that matters against its source.
            </strong>
          </>
        }
        title="Chat"
      >
        <p>
          No API key is involved on this screen, and no key issued by this
          platform can reach it.
        </p>
        <p>
          Select a <strong>capability</strong> rather than a model. The
          capability names the task and the platform selects the model that
          serves it, so a conversation remains valid when the models behind a
          name are replaced. Replies stream as they are produced, and{' '}
          <strong>Stop</strong> ends generation on the server rather than
          concealing the output.
        </p>
        <p>
          Two controls affect how a reply is produced.{' '}
          <strong>Thinking</strong> permits a deliberating model to reason
          before answering; clearing it requests a direct reply, which is the
          remedy where a model deliberates at length and produces no answer.{' '}
          <strong>Answer from the knowledge base</strong> draws the reply from
          the tenant&apos;s uploaded documents and is disabled unless enabled
          explicitly, so a reply is otherwise produced by the model alone.
          Prompt templates are not applied here; they are selected by callers
          using the API.
        </p>
        <p>
          On the caution above: presented with figures that did not determine a
          result, every model tested on this deployment produced a confident
          numerical answer, with the arithmetic set out, rather than reporting
          that the data were insufficient. This is a property of the models
          rather than of this platform. It is not corrected by selecting a
          different capability, and retrieval does not prevent it.
        </p>
      </PageHeader>
      <div className="min-h-0 flex-1">
        <ChatPanel />
      </div>
    </div>
  );
}
