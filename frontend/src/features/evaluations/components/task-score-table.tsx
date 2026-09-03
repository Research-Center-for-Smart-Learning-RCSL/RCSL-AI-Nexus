'use client';

import { Fragment, useState } from 'react';

import { cn } from '@/lib/utils';
import {
  VERDICT_DESCRIPTIONS,
  VERDICT_LABELS,
  countVerdicts,
  formatScore,
  indexTaskDefinitions,
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

/**
 * The question one task asked, opened underneath its own row.
 *
 * A score means very little without it. "This model got 0.42 on
 * `text_wrap_exact`" is not a fact anybody can act on until they can see that
 * the task states eleven interacting formatting rules and scores sixteen
 * independent assertions against them — and the run that produced the score is
 * the only place the exact wording still exists.
 *
 * Capped in height and scrolled rather than rendered whole: one of these
 * prompts is a 13,565-character policy document, and a table row that pushes
 * every other task off the screen makes the table unusable to reach it.
 */
function TaskPrompt({
  kind,
  checks,
  prompt,
  columns,
  id,
}: {
  kind: string;
  checks: number;
  prompt: string;
  columns: number;
  id: string;
}) {
  return (
    <tr>
      <td colSpan={columns} className="bg-muted/40 px-4 py-3">
        <div id={id} className="space-y-2">
          <p className="text-xs text-muted-foreground">
            {kind} · {checks} scoring unit{checks === 1 ? '' : 's'} ·{' '}
            {prompt.length.toLocaleString()} characters
          </p>
          <pre className="max-h-96 overflow-auto rounded-md bg-background p-3 text-xs leading-relaxed whitespace-pre-wrap">
            {prompt}
          </pre>
        </div>
      </td>
    </tr>
  );
}

export function TaskScoreTable({ report }: { report: EvaluationReport }) {
  const order = taskOrder(report);
  const scores = indexTaskScores(report);
  const counts = countVerdicts(report);
  const carrying = counts.discriminates;
  const definitions = indexTaskDefinitions(report);
  const [open, setOpen] = useState<string | null>(null);
  // Group, task, one per model, verdict.
  const columnCount = 3 + report.models.length;
  return (
    <section className="space-y-3">
      <h3 className="font-heading text-sm font-semibold">By task</h3>
      <p className="max-w-prose text-sm text-muted-foreground">
        <strong>
          {carrying} of {order.length} task{order.length === 1 ? '' : 's'}{' '}
          separated the models.
        </strong>{' '}
        The remainder were passed by every model, failed by every model, or
        scored too closely to distinguish them. A task that distinguishes no
        model contributes nothing to the ranking above, whatever number of such
        tasks a run contains. The denominator is every task the run named,
        including any it could not score, which carry no verdict at all.
      </p>
      {definitions.size > 0 ? (
        <p className="max-w-prose text-sm text-muted-foreground">
          Select a task name to read the question exactly as this run asked it.
          The wording is stored with the run rather than looked up, because a
          task gets rewritten and a score belongs to the version that produced
          it.
        </p>
      ) : null}
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
              const definition = definitions.get(task);
              const isOpen = open === task;
              const panelId = `task-prompt-${task}`;
              return (
                <Fragment key={task}>
                <tr>
                  <td className="py-2 pr-4 text-muted-foreground">{group}</td>
                  <td className="py-2 pr-4 font-mono text-xs">
                    {definition ? (
                      <button
                        type="button"
                        onClick={() => setOpen(isOpen ? null : task)}
                        aria-expanded={isOpen}
                        aria-controls={panelId}
                        className="cursor-pointer rounded-sm text-left underline decoration-dotted underline-offset-4 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                      >
                        {task}
                      </button>
                    ) : (
                      task
                    )}
                  </td>
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
                {isOpen && definition ? (
                  <TaskPrompt
                    id={panelId}
                    kind={definition.kind}
                    checks={definition.checks}
                    prompt={definition.prompt}
                    columns={columnCount}
                  />
                ) : null}
                </Fragment>
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
