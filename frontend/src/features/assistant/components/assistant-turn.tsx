import { SanitisedMarkdown } from '@/components/composed/stream-message';
import { cn } from '@/lib/utils';
import type { AssistantTurn as Turn } from '@/features/assistant/hooks/use-assistant';
import type { Proposal } from '@/features/assistant/schema';

import { ProposalCard } from './proposal-card';

export function AssistantTurn({
  turn,
  canApply,
  onApply,
}: {
  turn: Turn;
  canApply: boolean;
  onApply: (proposal: Proposal) => void;
}) {
  const isUser = turn.role === 'user';
  return (
    <div
      className={cn(
        'rounded-lg px-3 py-2 text-sm',
        isUser ? 'bg-muted' : 'ring-1 ring-foreground/10',
      )}
    >
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        {isUser ? 'You' : 'Assistant'}
      </p>
      {isUser ? (
        <p className="whitespace-pre-wrap">{turn.content}</p>
      ) : (
        <SanitisedMarkdown text={turn.content} />
      )}
      {turn.proposal ? (
        <ProposalCard
          proposal={turn.proposal}
          canApply={canApply}
          onApply={onApply}
        />
      ) : null}
      {turn.error ? (
        <p role="alert" className="mt-2 text-destructive">
          The answer stopped: {turn.error}
        </p>
      ) : null}
    </div>
  );
}
