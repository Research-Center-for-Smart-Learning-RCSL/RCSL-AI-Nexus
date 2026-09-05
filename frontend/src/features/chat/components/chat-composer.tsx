import type { FormEvent } from 'react';
import { InfoIcon } from 'lucide-react';
import { Popover } from '@base-ui/react/popover';

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
  CAPABILITY_DESCRIPTIONS,
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
        <ChatInfoPopover capability={capability} />
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

function ChatInfoPopover({ capability }: { capability: IssuableCapability }) {
  return (
    <Popover.Root>
      <Popover.Trigger
        render={
          <Button type="button" variant="ghost" size="icon-sm" aria-label="About this screen" />
        }
      >
        <InfoIcon className="size-3.5" />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner sideOffset={8} side="top" align="start">
          <Popover.Popup className="z-50 max-w-sm space-y-3 rounded-xl border bg-popover p-4 text-sm text-popover-foreground shadow-lg">
            <p>
              <strong>Capability:</strong> {CAPABILITY_DESCRIPTIONS[capability]}
            </p>
            <p>
              Select a <strong>capability</strong> rather than a model. The
              capability names the task and the platform selects the model that
              serves it, so a conversation remains valid when the models behind a
              name are replaced.
            </p>
            <p>
              <strong>Thinking</strong> permits a deliberating model to reason
              before answering; clearing it requests a direct reply.{' '}
              <strong>Knowledge base</strong> draws the reply from the
              tenant&apos;s uploaded documents.
            </p>
            <p className="text-muted-foreground">
              A model will answer a question its material cannot determine, so
              verify an answer that matters against its source.
            </p>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
