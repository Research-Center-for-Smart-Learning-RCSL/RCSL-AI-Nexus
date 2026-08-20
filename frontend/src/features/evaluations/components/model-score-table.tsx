import {
  formatRate,
  formatRoundSeconds,
  formatScore,
  type EvaluationReport,
} from '@/features/evaluations/schema';

function Cell({ children }: { children: React.ReactNode }) {
  return <td className="py-2 pr-4 tabular-nums">{children}</td>;
}

export function ModelScoreTable({ report }: { report: EvaluationReport }) {
  return (
    <section className="space-y-3">
      <h3 className="font-heading text-sm font-semibold">Overall</h3>
      <p className="max-w-prose text-sm text-muted-foreground">
        A model&apos;s score is the mean over the samples it <strong>answered</strong>.
        A sample that returned nothing at all — a truncated response, code that
        did not load — is counted separately rather than scored as zero, because
        a model that produced nothing and a model that answered badly are
        different findings.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-muted-foreground">
            <tr className="border-b">
              <th className="py-2 pr-4 font-medium">Model</th>
              <th className="py-2 pr-4 font-medium">Score</th>
              <th className="py-2 pr-4 font-medium">Scored</th>
              <th className="py-2 pr-4 font-medium">No result</th>
              <th className="py-2 pr-4 font-medium">Generation</th>
              <th className="py-2 pr-4 font-medium">Prompt depth</th>
              <th className="py-2 font-medium">Per round</th>
            </tr>
          </thead>
          <tbody className="[&_tr]:border-b">
            {report.models.map((model) => (
              <tr key={model.model_ref}>
                <td className="py-2 pr-4 font-mono text-xs">{model.model_ref}</td>
                <Cell><span className="font-medium">{formatScore(model.score)}</span></Cell>
                <Cell>{model.scored_samples}</Cell>
                <Cell>
                  <span className={model.no_result_samples > 0 ? 'text-destructive' : undefined}>
                    {model.no_result_samples}
                  </span>
                </Cell>
                <Cell>{formatRate(model.generation_tokens_per_second)}</Cell>
                <Cell>
                  {model.prompt_depth_tokens === null
                    ? '—'
                    : `${model.prompt_depth_tokens.toLocaleString()} tokens`}
                </Cell>
                <td className="py-2 tabular-nums">
                  {formatRoundSeconds(
                    model.seconds_per_round_min,
                    model.seconds_per_round_max,
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="max-w-prose text-sm text-muted-foreground">
        <strong>The generation rate travels with the prompt depth it was measured at</strong>,
        because a rate without a depth cannot be compared with another one.{' '}
        <strong>Per round</strong> is the wall clock for one full pass over the
        task set, and it is the more useful figure of the two: a model with the
        higher token rate can still take longer, because it writes more.
      </p>
    </section>
  );
}
