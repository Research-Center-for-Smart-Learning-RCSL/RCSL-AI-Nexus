import type { FormEvent } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

type AssistantComposerProps = {
  question: string;
  setQuestion: (question: string) => void;
  isStreaming: boolean;
  hasTurns: boolean;
  onSubmit: (event: FormEvent) => void;
  onCancel: () => void;
  onClear: () => void;
};

export function AssistantComposer({
  question,
  setQuestion,
  isStreaming,
  hasTurns,
  onSubmit,
  onCancel,
  onClear,
}: AssistantComposerProps) {
  return (
    <form
      onSubmit={onSubmit}
      className="flex items-center gap-2 border-t px-4 py-3"
    >
      <Input
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
        placeholder="Ask about this screen"
        disabled={isStreaming}
        className="flex-1"
        aria-label="Ask the assistant"
      />
      {isStreaming ? (
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Stop
        </Button>
      ) : (
        <Button type="submit" size="sm" disabled={!question.trim()}>
          Ask
        </Button>
      )}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={onClear}
        disabled={!hasTurns && !isStreaming}
      >
        Clear
      </Button>
    </form>
  );
}
