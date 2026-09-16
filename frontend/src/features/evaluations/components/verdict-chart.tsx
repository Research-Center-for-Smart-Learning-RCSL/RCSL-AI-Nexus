'use client';

import { cn } from '@/lib/utils';
import {
  VERDICT_LABELS,
  countVerdicts,
  taskOrder,
  type EvaluationReport,
  type TaskVerdict,
} from '@/features/evaluations/schema';

const VERDICT_BG: Record<TaskVerdict, string> = {
  discriminates: 'bg-primary',
  undecided: 'bg-amber-500/60',
  saturated_high: 'bg-muted-foreground/30',
  saturated_low: 'bg-destructive/60',
};

export function VerdictChart({ report }: { report: EvaluationReport }) {
  const counts = countVerdicts(report);
  const total = taskOrder(report).length;
  if (total === 0) return null;

  const order: TaskVerdict[] = ['discriminates', 'undecided', 'saturated_high', 'saturated_low'];
  const segments = order.filter((v) => counts[v] > 0);

  return (
    <section className="space-y-2">
      <h3 className="font-heading text-sm font-semibold">Task signal</h3>
      <div
        className="flex h-3 w-full overflow-hidden rounded-full bg-muted"
        role="img"
        aria-label={segments.map((v) => `${VERDICT_LABELS[v]}: ${counts[v]}`).join(', ')}
      >
        {segments.map((v) => (
          <div
            key={v}
            className={cn('h-full transition-all', VERDICT_BG[v])}
            style={{ width: `${(counts[v] / total) * 100}%` }}
            title={`${VERDICT_LABELS[v]}: ${counts[v]}`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {segments.map((v) => (
          <span key={v} className="inline-flex items-center gap-1.5">
            <span className={cn('size-2 rounded-full', VERDICT_BG[v])} />
            {VERDICT_LABELS[v]}: {counts[v]}
          </span>
        ))}
      </div>
    </section>
  );
}
