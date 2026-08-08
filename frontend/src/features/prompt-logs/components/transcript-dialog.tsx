'use client';

import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ErrorState } from '@/components/composed/error-state';
import { usePromptLogTranscript } from '@/features/prompt-logs/hooks/use-prompt-logs';
import { parseTranscriptTurns, type TranscriptTurn } from '@/features/prompt-logs/schema';

/**
 * One captured conversation, in full.
 *
 * **Everything here renders as plain text, never as markdown and never as
 * HTML.** This is the same rule a retrieved knowledge passage follows and for
 * a stronger reason: the content is a user's prompt and a model's completion,
 * both of which are attacker-influenced by definition — a caller controls the
 * prompt outright, and a model that has read a poisoned document controls part
 * of the answer. Rendering either would hand the one screen only an
 * administrator can reach a rendering surface driven by whoever made the
 * request being investigated. `<pre>` with `whitespace-pre-wrap` is the whole
 * of the treatment.
 *
 * Opening this dialog is what writes the `prompt_log.read` audit row, which is
 * why the fetch lives here rather than in the table: the record then
 * corresponds to a person deciding to read a conversation.
 */

const ROLE_TONE: Record<string, string> = {
  system: 'border-l-amber-500/60',
  user: 'border-l-sky-500/60',
  assistant: 'border-l-emerald-500/60',
  tool: 'border-l-violet-500/60',
};

function Turn({ turn, index }: { turn: TranscriptTurn; index: number }) {
  return (
    <li className={`border-l-2 pl-3 ${ROLE_TONE[turn.role] ?? 'border-l-foreground/20'}`}>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-mono font-medium text-foreground">{turn.role}</span>
        <span className="tabular-nums">#{index + 1}</span>
        {turn.name ? <span className="font-mono">{turn.name}</span> : null}
        {turn.tool_call_id ? (
          <span className="font-mono">answers {turn.tool_call_id}</span>
        ) : null}
      </div>
      {turn.content ? (
        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words font-mono text-xs">
          {turn.content}
        </pre>
      ) : null}
      {turn.tool_calls?.length ? (
        <ul className="mt-1 space-y-1">
          {turn.tool_calls.map((call) => (
            <li key={call.id} className="rounded bg-muted/50 p-2">
              <div className="font-mono text-xs font-medium">{call.name}</div>
              {/* The model's arguments as it produced them. Deliberately not
                  pretty-printed: they are stored as JSON text precisely so a
                  malformed call stays replayable, and reformatting would hide
                  the malformation somebody opened this to see. */}
              <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-xs text-muted-foreground">
                {call.arguments}
              </pre>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function Section({ title, body }: { title: string; body: string }) {
  return (
    <section className="space-y-1">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 p-3 font-mono text-xs">
        {body}
      </pre>
    </section>
  );
}

export function TranscriptDialog({
  id,
  onOpenChange,
}: {
  id: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { data, isLoading, error, refetch } = usePromptLogTranscript(id);
  const turns = data ? parseTranscriptTurns(data.messages) : null;

  return (
    <Dialog open={id !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Transcript</DialogTitle>
          <DialogDescription>
            The prompt as the model received it, after any template and
            retrieved passages were merged in, and what it wrote back. Opening
            this recorded who read it.
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <div className="space-y-2" aria-busy="true">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-4 w-full animate-pulse rounded bg-muted" />
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="secondary">{data.capability}</Badge>
              <span className="font-mono text-muted-foreground">{data.model_alias}</span>
              <span className="text-muted-foreground tabular-nums">
                {new Date(data.at).toLocaleString()}
              </span>
              {data.request_id ? (
                <span className="font-mono text-muted-foreground">{data.request_id}</span>
              ) : null}
              {!data.completed ? (
                <Badge variant="destructive">
                  incomplete{data.finish_reason ? `: ${data.finish_reason}` : ''}
                </Badge>
              ) : null}
              {data.truncated_fields.length > 0 ? (
                <Badge variant="destructive">
                  cut: {data.truncated_fields.join(', ')}
                </Badge>
              ) : null}
            </div>

            <section className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Prompt
              </h3>
              {turns ? (
                <ol className="space-y-3">
                  {turns.map((turn, i) => (
                    <Turn key={i} turn={turn} index={i} />
                  ))}
                </ol>
              ) : (
                // Shown raw rather than thrown away. A transcript that will not
                // parse is still evidence, and an error where the evidence
                // should be is the worse outcome.
                <Section title="Unparsed" body={data.messages} />
              )}
            </section>

            {data.reasoning ? (
              // Apart from the answer, because it is not the answer — the same
              // separation the wire format keeps. A model can spend its whole
              // token budget here.
              <Section title="Reasoning" body={data.reasoning} />
            ) : null}

            <Section
              title="Completion"
              body={data.completion || '(the model produced no text)'}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
