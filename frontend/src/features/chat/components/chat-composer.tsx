import type { FormEvent } from 'react';

import { ComposerTextarea } from '@/components/composed/composer-textarea';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  isConversational,
  issuableCapabilitySchema,
  type IssuableCapability,
} from '@/features/models/schema';

type ChatComposerProps = {
  capability: IssuableCapability;
  setCapability: (capability: IssuableCapability) => void;
  thinking: boolean;
  setThinking: (thinking: boolean) => void;
  prompt: string;
  setPrompt: (prompt: string) => void;
  useKnowledge: boolean;
  setUseKnowledge: (useKnowledge: boolean) => void;
  isStreaming: boolean;
  gatewayLoading: boolean;
  servable: ReadonlySet<string>;
  hasContent: boolean;
  onSubmit: (event: FormEvent) => void;
  onCancel: () => void;
  onClear: () => void;
};

export function ChatComposer(props: ChatComposerProps) {
  const {
    capability,
    setCapability,
    thinking,
    setThinking,
    prompt,
    setPrompt,
    useKnowledge,
    setUseKnowledge,
    isStreaming,
    gatewayLoading,
    servable,
    hasContent,
    onSubmit,
    onCancel,
    onClear,
  } = props;
  return (
    <form onSubmit={onSubmit} className="space-y-2">
      <div data-slot="chat-composer-settings" className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Select
          value={capability}
          onValueChange={(value) => setCapability(value as IssuableCapability)}
        >
          <SelectTrigger className="min-w-36 flex-1 sm:flex-none" aria-label="Capability">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {issuableCapabilitySchema.options.map((option) => {
              const routable =
                gatewayLoading || servable.has(option) || option === capability;
              return (
                <SelectItem
                  key={option}
                  value={option}
                  disabled={!isConversational(option) || !routable}
                >
                  {option}
                  {isConversational(option) ? null : (
                    <span className="text-xs text-muted-foreground">
                      not a conversation
                    </span>
                  )}
                  {isConversational(option) && !routable ? (
                    <span className="text-xs text-muted-foreground">
                      nothing serves this yet
                    </span>
                  ) : null}
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
        <label className="flex shrink-0 items-center gap-1.5 text-sm text-muted-foreground">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={thinking}
            disabled={isStreaming}
            onChange={(event) => setThinking(event.target.checked)}
          />
          Thinking
        </label>
        <label className="flex shrink-0 items-center gap-1.5 text-sm text-muted-foreground">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={useKnowledge}
            disabled={isStreaming}
            onChange={(event) => setUseKnowledge(event.target.checked)}
          />
          Knowledge base
        </label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="ml-auto"
          onClick={onClear}
          disabled={!hasContent}
        >
          Clear
        </Button>
      </div>
      <div data-slot="chat-composer-writing" className="flex items-end gap-2">
        <ComposerTextarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Ask something"
          disabled={isStreaming}
          className="flex-1"
          aria-label="Message"
          aria-describedby="chat-composer-keyboard-hint"
        />
        {isStreaming ? (
          <Button type="button" variant="outline" onClick={onCancel}>
            Stop
          </Button>
        ) : (
          <Button type="submit" disabled={!prompt.trim()}>
            Send
          </Button>
        )}
      </div>
      <p
        id="chat-composer-keyboard-hint"
        className="text-xs text-muted-foreground"
      >
        Enter to send · Shift+Enter for a new line
      </p>
    </form>
  );
}
