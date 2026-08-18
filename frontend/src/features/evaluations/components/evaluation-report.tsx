'use client';

/**
 * One stored run: what it measured, and what it does not establish.
 *
 * **The caveats are rendered before the tables, not after them.** They come
 * from the run rather than from this file (`EvaluationRun.caveats`), and the
 * order is the argument: a reader who sees a ranking first has already formed
 * a view by the time the limits arrive. How many tasks carried no signal is
 * the sentence that decides how much the ranking under it is worth, and on
 * these runs it is most of them.
 *
 * The count itself is computed from the report rather than written here. An
 * earlier version of this comment quoted the figure from the progress log,
 * which was that run's pre-repair reading and two off what the table prints.
 *
 * Every figure is read from the report. Nothing here restates a number, which
 * is the rule `host-numbers-explainer` follows for the same reason: a page that
 * repeats a value acquires a second source of truth and diverges from the
 * first.
 */

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  VERDICT_DESCRIPTIONS,
  VERDICT_LABELS,
  countVerdicts,
  formatRate,
  formatRoundSeconds,
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

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : '—';
}

function Cell({ children }: { children: React.ReactNode }) {
  return <td className="py-2 pr-4 tabular-nums">{children}</td>;
}

export function EvaluationReportView({ report }: { report: EvaluationReport }) {
  const { run, models } = report;
  const order = taskOrder(report);
  const scores = indexTaskScores(report);
  const counts = countVerdicts(report);
  // The one figure the reader needs before the ranking means anything: how
  // many of the tasks actually told the models apart.
  const carrying = counts.discriminates;

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="font-heading text-base font-semibold">{run.label}</h2>
          <Badge variant="outline">{run.phase}</Badge>
          <span className="text-sm text-muted-foreground">
            ran {formatDate(run.ran_at)}
          </span>
        </div>
        {run.note ? (
          <p className="max-w-prose text-sm text-muted-foreground">{run.note}</p>
        ) : null}
        <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[9rem_1fr]">
          <dt className="text-muted-foreground">Samples</dt>
          <dd className="tabular-nums">
            {run.sample_count.toLocaleString()} across {models.length} model
            {models.length === 1 ? '' : 's'} and {order.length} task
            {order.length === 1 ? '' : 's'}
          </dd>
          <dt className="text-muted-foreground">Harness</dt>
          <dd className="font-mono text-xs">{run.harness_ref || '—'}</dd>
          <dt className="text-muted-foreground">Loaded</dt>
          <dd>
            {formatDate(run.imported_at)}
            {run.imported_by ? ` by ${run.imported_by}` : ''}
          </dd>
        </dl>
      </section>

      {/* Before the tables, deliberately. See the note at the top of this file.
          Rendered whether or not the run carries any, because `--caveat` is
          optional at import: a run loaded without one would otherwise show a
          ranking with no statement of limits at all, which is the shape this
          section exists to prevent and reads as a run that has none. */}
      <section className="max-w-prose space-y-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
        <h3 className="font-heading text-sm font-semibold">
          What this run does not establish
        </h3>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          {run.caveats.length ? (
            run.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)
          ) : (
            <li>
              Whoever imported this run recorded no limits against it. That is
              an omission at import rather than a statement that the run has
              none — read the per-task verdicts below before relying on the
              ranking.
            </li>
          )}
        </ul>
      </section>

      <section className="space-y-3">
        <h3 className="font-heading text-sm font-semibold">Overall</h3>
        <p className="max-w-prose text-sm text-muted-foreground">
          A model&apos;s score is the mean over the samples it{' '}
          <strong>answered</strong>. A sample that returned nothing at all —
          a truncated response, code that did not load — is counted separately
          rather than scored as zero, because a model that produced nothing and
          a model that answered badly are different findings.
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
              {models.map((model) => (
                <tr key={model.model_ref}>
                  <td className="py-2 pr-4 font-mono text-xs">{model.model_ref}</td>
                  <Cell>
                    <span className="font-medium">{formatScore(model.score)}</span>
                  </Cell>
                  <Cell>{model.scored_samples}</Cell>
                  <Cell>
                    <span
                      className={
                        model.no_result_samples > 0 ? 'text-destructive' : undefined
                      }
                    >
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
          <strong>The generation rate travels with the prompt depth it was
          measured at</strong>, because a rate without a depth cannot be
          compared with another one. <strong>Per round</strong> is the wall
          clock for one full pass over the task set, and it is the more useful
          figure of the two: a model with the higher token rate can still take
          longer, because it writes more.
        </p>
      </section>

      <section className="space-y-3">
        <h3 className="font-heading text-sm font-semibold">By task</h3>
        <p className="max-w-prose text-sm text-muted-foreground">
          <strong>
            {carrying} of {order.length} task{order.length === 1 ? '' : 's'}{' '}
            separated the models.
          </strong>{' '}
          The rest were passed by everyone, failed by everyone, or scored too
          close together to tell the models apart, and a task nobody is
          distinguished by contributes nothing to the ranking above, however
          many of them there are. The denominator is every task the run named,
          including any it could not score — those carry no verdict at all.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted-foreground">
              <tr className="border-b">
                <th className="py-2 pr-4 font-medium">Group</th>
                <th className="py-2 pr-4 font-medium">Task</th>
                {models.map((model) => (
                  <th key={model.model_ref} className="py-2 pr-4 font-medium">
                    {/* The whole reference. Truncating at the colon collapsed
                        `qwen3.6:27b-q8_0` and `qwen3.6:35b-a3b-q8_0` into two
                        adjacent columns both headed `qwen3.6`, on the one run
                        this screen was built to show — and the tag is exactly
                        the part that was measured, since an alias is a name an
                        operator may repoint at different weights. */}
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
                    {models.map((model) => {
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
    </div>
  );
}
