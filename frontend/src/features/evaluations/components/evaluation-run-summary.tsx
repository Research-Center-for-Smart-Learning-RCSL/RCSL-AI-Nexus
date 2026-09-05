import { Badge } from '@/components/ui/badge';
import { taskOrder, type EvaluationReport } from '@/features/evaluations/schema';

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : '—';
}

export function EvaluationRunSummary({ report }: { report: EvaluationReport }) {
  const { run, models } = report;
  const order = taskOrder(report);
  return (
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
  );
}

export function EvaluationCaveats({ report }: { report: EvaluationReport }) {
  if (!report.run.caveats.length) return null;
  return (
    <details className="max-w-prose rounded-lg border border-amber-500/40 bg-amber-500/5">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium hover:text-foreground">
        What this run does not establish
        <span className="ml-2 text-xs text-muted-foreground">
          ({report.run.caveats.length} caveat
          {report.run.caveats.length === 1 ? '' : 's'})
        </span>
      </summary>
      <ul className="list-disc space-y-1 px-4 pb-3 pl-9 text-sm text-muted-foreground">
        {report.run.caveats.map((caveat) => (
          <li key={caveat}>{caveat}</li>
        ))}
      </ul>
    </details>
  );
}
