import type { MutableStreamStore } from '@/components/composed/stream-message';
import { describeError } from '@/components/composed/error-state';
import { openAssistantStream } from '@/features/assistant/api';
import {
  readProposalFrame,
  type ApiKeyDraft,
  type AssistMessage,
  type AssistSurface,
  type Proposal,
} from '@/features/assistant/schema';
import { readChatStream } from '@/features/chat/stream';

type AssistantRequest = {
  surface: AssistSurface;
  messages: AssistMessage[];
  draft: ApiKeyDraft | undefined;
  keyId: string | undefined;
  signal: AbortSignal;
  store: MutableStreamStore;
};

export type AssistantRequestResult = {
  proposal: Proposal | null;
  answer: string;
  failure: string | undefined;
  finishReason: string | undefined;
};

export async function runAssistantRequest({
  surface,
  messages,
  draft,
  keyId,
  signal,
  store,
}: AssistantRequest): Promise<AssistantRequestResult> {
  let proposal: Proposal | null = null;
  let answer = '';
  let failure: string | undefined;
  let finishReason: string | undefined;

  try {
    const response = await openAssistantStream(
      { surface, messages, draft, key_id: keyId },
      signal,
    );
    await readChatStream(
      response,
      {
        onDelta: (text) => {
          answer += text;
          store.append(text);
        },
        onError: (message) => {
          failure = message;
          store.fail(message);
        },
        onDone: (reason) => {
          finishReason = reason ?? undefined;
          store.finish(reason);
        },
        onTrailer: (raw) => {
          const found = readProposalFrame(raw);
          if (found) proposal = found;
        },
      },
      signal,
    );
  } catch (caught) {
    if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
      failure = describeError(caught);
      store.fail(failure);
    }
  }

  return { proposal, answer, failure, finishReason };
}
