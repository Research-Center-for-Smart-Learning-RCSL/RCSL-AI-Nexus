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
  shortModelLabel,
  taskKey,
  tasksByGroup,
  type EvaluationReport,
  type TaskVerdict,
} from '@/features/evaluations/schema';

const VERDICT_TONE: Record<TaskVerdict, string> = {
  discriminates: 'text-foreground',
  saturated_high: 'text-muted-foreground/60',
  saturated_low: 'text-destructive',
  undecided: 'text-muted-foreground',
};

function ScoreCell({
  score,
  verdict,
}: {
  score: number | null;
  verdict?: TaskVerdict;
}) {
  const isSaturated =
    verdict === 'saturated_high' || verdict === 'saturated_low';
  return (
    <td
      className={cn(
        'py-2 pr-4 tabular-nums',
        isSaturated && 'text-muted-foreground/50',
      )}
    >
      {score === null ? (
        <span className="text-muted-foreground">—</span>
      ) : (
        <span
          className={cn(
            score === 1.0 && 'text-green-600 dark:text-green-400',
            score === 0.0 && 'text-destructive',
          )}
        >
          {formatScore(score)}
        </span>
      )}
    </td>
  );
}

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
  const groups = tasksByGroup(report);
  const scores = indexTaskScores(report);
  const counts = countVerdicts(report);
  const definitions = indexTaskDefinitions(report);
  const [open, setOpen] = useState<string | null>(null);
  const [showSaturated, setShowSaturated] = useState(false);
  const columnCount = 3 + report.models.length;

  const allTasks = groups.flatMap((g) => g.tasks);
  const signalTasks = allTasks.filter((t) => {
    const v = report.verdicts[t.task];
    return v === 'discriminates' || v === 'undecided';
  });
  const unscoredTasks = allTasks.filter(
    (t) => !(t.task in report.verdicts),
  );
  const saturatedTasks = allTasks.filter((t) => {
    const v = report.verdicts[t.task];
    return v === 'saturated_high' || v === 'saturated_low';
  });

  function renderTaskRow(entry: { task: string; group: string }) {
    const verdict = report.verdicts[entry.task];
    const definition = definitions.get(entry.task);
    const isOpen = open === entry.task;
    const panelId = `task-prompt-${entry.task}`;

    return (
      <Fragment key={entry.task}>
        <tr
          className={cn(
            verdict === 'saturated_high' && 'opacity-50',
            verdict === 'saturated_low' && 'opacity-70',
          )}
        >
          <td className="py-2 pr-4 text-xs text-muted-foreground">
            {entry.group}
          </td>
          <td className="py-2 pr-4 font-mono text-xs">
            {definition ? (
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : entry.task)}
                aria-expanded={isOpen}
                aria-controls={panelId}
                className="cursor-pointer rounded-sm text-left underline decoration-dotted underline-offset-4 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                {entry.task}
              </button>
            ) : (
              entry.task
            )}
          </td>
          {report.models.map((model) => {
            const e = scores.get(taskKey(entry.task, model.model_ref));
            return (
              <ScoreCell
                key={model.model_ref}
                score={e?.score ?? null}
                verdict={verdict}
              />
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
              <span className="text-xs text-muted-foreground">Not scored</span>
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
  }

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h3 className="font-heading text-sm font-semibold">By task</h3>
        <p className="max-w-prose text-sm text-muted-foreground">
          <strong>
            {counts.discriminates} of {allTasks.length} tasks separated the
            models.
          </strong>{' '}
          Tasks that every model passed or every model failed contribute nothing
          to the ranking.
          {definitions.size > 0
            ? ' Select a task name to read the question as this run asked it.'
            : ''}
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-muted-foreground">
            <tr className="border-b">
              <th className="py-2 pr-4 font-medium">Group</th>
              <th className="py-2 pr-4 font-medium">Task</th>
              {report.models.map((model) => (
                <th key={model.model_ref} className="py-2 pr-4 font-medium">
                  <span
                    className="font-mono text-xs"
                    title={model.model_ref}
                  >
                    {shortModelLabel(model.model_ref)}
                  </span>
                </th>
              ))}
              <th className="py-2 font-medium">Verdict</th>
            </tr>
          </thead>
          <tbody className="[&_tr]:border-b">
            {signalTasks.length > 0 && (
              <tr>
                <td
                  colSpan={columnCount}
                  className="bg-primary/5 py-1.5 pl-3 text-xs font-medium text-primary"
                >
                  Tasks that separate the models ({signalTasks.length})
                </td>
              </tr>
            )}
            {signalTasks.map((t) => renderTaskRow(t))}

            {unscoredTasks.length > 0 && (
              <tr>
                <td
                  colSpan={columnCount}
                  className="py-1.5 pl-3 text-xs text-muted-foreground"
                >
                  Not scored ({unscoredTasks.length})
                </td>
              </tr>
            )}
            {unscoredTasks.map((t) => renderTaskRow(t))}

            {saturatedTasks.length > 0 && (
              <tr>
                <td colSpan={columnCount} className="py-1.5 pl-3">
                  <button
                    type="button"
                    onClick={() => setShowSaturated(!showSaturated)}
                    className="cursor-pointer text-xs text-muted-foreground hover:text-foreground"
                  >
                    {showSaturated ? '▾' : '▸'} Saturated tasks (
                    {saturatedTasks.length}) — every model passed or every model
                    failed
                  </button>
                </td>
              </tr>
            )}
            {showSaturated &&
              saturatedTasks.map((t) => renderTaskRow(t))}
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
