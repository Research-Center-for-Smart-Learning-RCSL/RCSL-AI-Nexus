'use client';

/**
 * The evaluation screen: which run is being read, and the run itself.
 *
 * Opens on the newest run rather than on a picker, because "what is the current
 * reading" is the question somebody arrives with; the picker appears only when
 * there is more than one run to choose between, since a select with a single
 * option is a control that asks a question with one answer.
 *
 * **An empty state here is a normal deployment, not a fault.** Running the task
 * set is an afternoon's work that nobody owes anyone, so a platform with no
 * evaluation says so plainly and points at the harness, rather than reporting
 * the absence as an error.
 */

import { useState } from 'react';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { EmptyState } from '@/components/composed/empty-state';
import { ErrorState } from '@/components/composed/error-state';
import { Spinner } from '@/components/composed/spinner';
import { EvaluationReportView } from '@/features/evaluations/components/evaluation-report';
import {
  useEvaluationReport,
  useEvaluationRuns,
  useLatestEvaluation,
} from '@/features/evaluations/hooks/use-evaluations';

export function EvaluationView() {
  const runs = useEvaluationRuns();
  const latest = useLatestEvaluation();
  // Null means "whichever is newest", which is what the screen opens on. A
  // chosen id switches to the second query; the first is never refetched for
  // it, so going back to the newest run costs nothing.
  const [chosen, setChosen] = useState<string | null>(null);
  const chosenReport = useEvaluationReport(chosen);

  const error = runs.error ?? latest.error ?? chosenReport.error;
  if (error) {
    return (
      <ErrorState
        title="Could not load the evaluations"
        error={error}
        onRetry={() => {
          void runs.refetch();
          void latest.refetch();
        }}
      />
    );
  }

  if (latest.isLoading || runs.isLoading) {
    return <Spinner label="Loading the evaluation" />;
  }

  if (!latest.data) {
    return (
      <EmptyState
        title="No evaluation has been run here"
        description="The task set in scripts/model-eval measures what a model does on tasks a program can check. Run it and load the result, and it appears here. A deployment without one is in a normal state: nothing on this platform depends on an evaluation existing."
      />
    );
  }

  const report = chosen ? chosenReport.data : latest.data;
  const options = runs.data ?? [];

  return (
    <div className="space-y-6">
      {options.length > 1 ? (
        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor="evaluation-run"
            className="text-sm text-muted-foreground"
          >
            Run
          </label>
          <Select
            value={chosen ?? latest.data.run.id}
            onValueChange={(value) => setChosen(value)}
          >
            <SelectTrigger id="evaluation-run" className="w-80">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.map((run) => (
                <SelectItem key={run.id} value={run.id}>
                  {run.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-xs text-muted-foreground">
            {options.length} runs stored. Older runs are kept as they were; a
            re-import corrects a run rather than adding a second copy of it.
          </span>
        </div>
      ) : null}

      {report ? (
        <EvaluationReportView report={report} />
      ) : (
        <Spinner label="Loading that run" />
      )}
    </div>
  );
}
