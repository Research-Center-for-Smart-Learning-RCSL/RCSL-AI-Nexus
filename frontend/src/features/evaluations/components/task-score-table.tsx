import { cn } from '@/lib/utils';
import {
  VERDICT_DESCRIPTIONS,
  VERDICT_LABELS,
  countVerdicts,
  formatScore,
  indexTaskScores,
  taskKey,
  taskOrder,
  type EvaluationReport,
  type TaskVerdict,
} from '@/features/evaluations/schema';

const VERDICT_TONE: Record<TaskVerdict, string> = {
  discriminates: 'text-foreground',
  saturated_high: 'text-muted-foreground',
  saturated_low: 'text-destructive',
  undecided: 'text-muted-foreground',
};

function Cell({ children }: { children: React.ReactNode }) {
  return <td className="py-2 pr-4 tabular-nums">{children}</td>;
}

export function TaskScoreTable({ report }: { report: EvaluationReport }) {
  const order = taskOrder(report);
  const scores = indexTaskScores(report);
  const counts = countVerdicts(report);
  const carrying = counts.discriminates;
  return (
    <section className="space-y-3">
      <h3 className="font-heading text-sm font-semibold">By task</h3>
      <p className="max-w-prose text-sm text-muted-foreground">
        <strong>
          {carrying} of {order.length} task{order.length === 1 ? '' : 's'}{' '}
          separated the models.
        </strong>{' '}
        The rest were passed by everyone, failed by everyone, or scored too
        close together to tell the models apart, and a task nobody is
        distinguished by contributes nothing to the ranking above, however many
        of them there are. The denominator is every task the run named,
        including any it could not score — those carry no verdict at all.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-muted-foreground">
            <tr className="border-b">
              <th className="py-2 pr-4 font-medium">Group</th>
              <th className="py-2 pr-4 font-medium">Task</th>
              {report.models.map((model) => (
                <th key={model.model_ref} className="py-2 pr-4 font-medium">
                  <span className="font-mono text-xs break-all">
                    {model.model_ref}
                  </span>
                </th>
              ))}
              <th className="py-2 font-medium">Verdict</th>
            </tr>
          </thead>
          <tbody className="[&_tr]:border-b">
            {order.map(({ task, group }) => {
              const verdict = report.verdicts[task];
              return (
                <tr key={task}>
                  <td className="py-2 pr-4 text-muted-foreground">{group}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{task}</td>
                  {report.models.map((model) => {
                    const entry = scores.get(taskKey(task, model.model_ref));
                    return (
                      <Cell key={model.model_ref}>
                        {entry ? formatScore(entry.score) : '—'}
                      </Cell>
                    );
                  })}
                  <td className="py-2">
                    {verdict ? (
                      <span
                        className={cn('text-xs', VERDICT_TONE[verdict])}
                        title={VERDICT_DESCRIPTIONS[verdict]}
                      >
                        {VERDICT_LABELS[verdict]}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        Not scored
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <dl className="max-w-prose grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[11rem_1fr]">
        {(Object.keys(VERDICT_LABELS) as TaskVerdict[]).map((verdict) => (
          <div key={verdict} className="contents">
            <dt className={cn('font-medium', VERDICT_TONE[verdict])}>
              {VERDICT_LABELS[verdict]}
              <span className="ml-2 font-normal text-muted-foreground tabular-nums">
                {counts[verdict]}
              </span>
            </dt>
            <dd className="text-muted-foreground">
              {VERDICT_DESCRIPTIONS[verdict]}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
