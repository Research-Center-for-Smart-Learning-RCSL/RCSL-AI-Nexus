import type { EvaluationReport } from '@/features/evaluations/schema';

import {
  EvaluationCaveats,
  EvaluationRunSummary,
} from './evaluation-run-summary';
import { ModelScoreTable } from './model-score-table';
import { TaskScoreTable } from './task-score-table';

export function EvaluationReportView({ report }: { report: EvaluationReport }) {
  return (
    <div className="space-y-8">
      <EvaluationRunSummary report={report} />
      <EvaluationCaveats report={report} />
      <ModelScoreTable report={report} />
      <TaskScoreTable report={report} />
    </div>
  );
}
