import { cn } from '@/lib/utils';
import {
  formatRate,
  formatRoundSeconds,
  formatScore,
  shortModelLabel,
  taskOrder,
  type EvaluationReport,
} from '@/features/evaluations/schema';

function ScoreBar({ score, best }: { score: number | null; best: number }) {
  if (score === null) return <span className="text-muted-foreground">—</span>;
  const pct = score * 100;
  const isBest = best > 0 && Math.abs(score - best) < 0.001;
  return (
    <div className="flex items-center gap-3">
      <div className="h-2.5 w-full max-w-48 rounded-full bg-muted">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            isBest ? 'bg-primary' : 'bg-primary/40',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span
        className={cn(
          'tabular-nums text-sm font-medium',
          isBest && 'text-primary',
        )}
      >
        {formatScore(score)}
      </span>
    </div>
  );
}

export function ModelScoreTable({ report }: { report: EvaluationReport }) {
  const best = Math.max(...report.models.map((m) => m.score ?? 0));
  const order = taskOrder(report);
  const totalTasks = order.length;
  const signalCount = order.filter(
    (t) => report.verdicts[t.task] === 'discriminates',
  ).length;

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h3 className="font-heading text-sm font-semibold">Model comparison</h3>
        <p className="text-sm text-muted-foreground">
          <strong>{signalCount}</strong> of {totalTasks} tasks separated the
          models. The ranking rests on those tasks alone.
        </p>
      </div>

      <div className="space-y-3">
        {report.models
          .slice()
          .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
          .map((model) => (
            <div key={model.model_ref} className="flex items-center gap-4">
              <div className="w-32 shrink-0 truncate text-right">
                <span className="font-mono text-xs" title={model.model_ref}>
                  {shortModelLabel(model.model_ref)}
                </span>
              </div>
              <div className="flex-1">
                <ScoreBar score={model.score} best={best} />
              </div>
              <div className="hidden shrink-0 gap-4 text-xs text-muted-foreground tabular-nums sm:flex">
                <span title="Generation speed">
                  {formatRate(model.generation_tokens_per_second)}
                </span>
                <span title="Wall clock per round">
                  {formatRoundSeconds(
                    model.seconds_per_round_min,
                    model.seconds_per_round_max,
                  )}
                </span>
              </div>
            </div>
          ))}
      </div>

      <details className="group">
        <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
          Full metrics table
        </summary>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted-foreground">
              <tr className="border-b">
                <th className="py-2 pr-4 font-medium">Model</th>
                <th className="py-2 pr-4 font-medium">Score</th>
                <th className="py-2 pr-4 font-medium">Scored</th>
                <th className="py-2 pr-4 font-medium">No result</th>
                <th className="py-2 pr-4 font-medium">Generation</th>
                <th className="py-2 pr-4 font-medium">Depth</th>
                <th className="py-2 font-medium">Per round</th>
              </tr>
            </thead>
            <tbody className="[&_tr]:border-b">
              {report.models.map((model) => (
                <tr key={model.model_ref}>
                  <td className="py-2 pr-4 font-mono text-xs">
                    {model.model_ref}
                  </td>
                  <td className="py-2 pr-4 tabular-nums font-medium">
                    {formatScore(model.score)}
                  </td>
                  <td className="py-2 pr-4 tabular-nums">
                    {model.scored_samples}
                  </td>
                  <td className="py-2 pr-4 tabular-nums">
                    <span
                      className={
                        model.no_result_samples > 0
                          ? 'text-destructive'
                          : undefined
                      }
                    >
                      {model.no_result_samples}
                    </span>
                  </td>
                  <td className="py-2 pr-4 tabular-nums">
                    {formatRate(model.generation_tokens_per_second)}
                  </td>
                  <td className="py-2 pr-4 tabular-nums">
                    {model.prompt_depth_tokens === null
                      ? '—'
                      : `${model.prompt_depth_tokens.toLocaleString()} tok`}
                  </td>
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
      </details>
    </section>
  );
}
