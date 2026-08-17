import { api } from '@/lib/api-client';
import {
  evaluationReportSchema,
  evaluationRunListSchema,
  latestEvaluationSchema,
  type EvaluationReport,
  type EvaluationRun,
} from '@/features/evaluations/schema';

const BASE = '/evaluations';

export async function listEvaluationRuns(): Promise<EvaluationRun[]> {
  return evaluationRunListSchema.parse(await api.get<unknown>(BASE));
}

/**
 * The newest run, or null where the task set has never been run here.
 *
 * Null is a real answer rather than an error: running the set is an
 * afternoon's work nobody owes anyone, and a deployment without one is in a
 * normal state that the screen says plainly.
 */
export async function latestEvaluation(): Promise<EvaluationReport | null> {
  return latestEvaluationSchema.parse(await api.get<unknown>(`${BASE}/latest`));
}

export async function getEvaluation(runId: string): Promise<EvaluationReport> {
  return evaluationReportSchema.parse(
    await api.get<unknown>(`${BASE}/${encodeURIComponent(runId)}`),
  );
}
