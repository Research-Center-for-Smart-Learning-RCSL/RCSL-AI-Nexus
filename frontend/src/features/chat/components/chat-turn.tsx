import {
  describeEmptyOutcome,
  ReasoningBlock,
  SanitisedMarkdown,
} from '@/components/composed/stream-message';
import { cn } from '@/lib/utils';
import type { ChatTurn as Turn } from '@/features/chat/hooks/use-chat-stream';

export function ChatTurn({ turn }: { turn: Turn }) {
  const isUser = turn.role === 'user';
  const outcome = turn.content
    ? null
    : describeEmptyOutcome(
        turn.finishReason ?? null,
        turn.elapsedMs ?? null,
      );
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
          <ReasoningBlock
            text={turn.reasoning ?? ''}
            defaultOpen={!turn.content}
            elapsedMs={turn.elapsedMs ?? null}
          />
          {turn.content ? (
            <SanitisedMarkdown text={turn.content} />
          ) : outcome ? (
            <p className="text-sm text-muted-foreground">{outcome}</p>
          ) : null}
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
