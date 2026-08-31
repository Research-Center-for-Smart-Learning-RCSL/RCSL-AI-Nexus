import type { FormEvent } from 'react';

import { ComposerTextarea } from '@/components/composed/composer-textarea';
import { Button } from '@/components/ui/button';

type AssistantComposerProps = {
  question: string;
  setQuestion: (question: string) => void;
  isStreaming: boolean;
  onSubmit: (event: FormEvent) => void;
  onCancel: () => void;
};

export function AssistantComposer({
  question,
  setQuestion,
  isStreaming,
  onSubmit,
  onCancel,
}: AssistantComposerProps) {
  return (
    <form
      onSubmit={onSubmit}
      className="border-t px-4 py-3"
    >
      <div className="flex items-end gap-2">
        <ComposerTextarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about this screen"
          disabled={isStreaming}
          className="flex-1"
          aria-label="Ask the assistant"
          aria-describedby="assistant-composer-keyboard-hint"
        />
        {isStreaming ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="min-w-12"
            onClick={onCancel}
          >
            Stop
          </Button>
        ) : (
          <Button
            type="submit"
            size="sm"
            className="min-w-12"
            disabled={!question.trim()}
          >
            Ask
          </Button>
        )}
      </div>
      <p
        id="assistant-composer-keyboard-hint"
        className="mt-1.5 text-xs text-muted-foreground"
      >
        Enter to ask · Shift+Enter for a new line
      </p>
    </form>
  );
}
