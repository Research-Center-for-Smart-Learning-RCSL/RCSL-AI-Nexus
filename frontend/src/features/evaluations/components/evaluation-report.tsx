import type { EvaluationReport } from '@/features/evaluations/schema';

import {
  EvaluationCaveats,
  EvaluationRunSummary,
} from './evaluation-run-summary';
import { ModelScoreChart } from './model-score-chart';
import { ModelScoreTable } from './model-score-table';
import { TaskHeatmap } from './task-heatmap';
import { TaskScoreTable } from './task-score-table';
import { VerdictChart } from './verdict-chart';

export function EvaluationReportView({ report }: { report: EvaluationReport }) {
  return (
    <div className="space-y-8">
      <EvaluationRunSummary report={report} />
      <EvaluationCaveats report={report} />
      <VerdictChart report={report} />
      <ModelScoreChart report={report} />
      <ModelScoreTable report={report} />
      <TaskHeatmap report={report} />
      <TaskScoreTable report={report} />
    </div>
  );
}
