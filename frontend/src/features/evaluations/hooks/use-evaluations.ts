'use client';

import { useQuery } from '@tanstack/react-query';

import {
  getEvaluation,
  latestEvaluation,
  listEvaluationRuns,
} from '@/features/evaluations/api';

export const evaluationKeys = {
  all: ['evaluations'] as const,
  latest: () => [...evaluationKeys.all, 'latest'] as const,
  report: (runId: string) => [...evaluationKeys.all, 'report', runId] as const,
};

/**
 * Long-lived by design.
 *
 * A stored evaluation is a record of something that happened on a day, not a
 * live figure: nothing on the platform can change it between two renders, and
 * the only event that does is an import an operator performs deliberately. So
 * these are cached for the session rather than refetched on every focus, which
 * is the opposite of what the host panel beside them wants.
 */
const STALE_MS = 5 * 60_000;

export function useEvaluationRuns() {
  return useQuery({
    queryKey: evaluationKeys.all,
    queryFn: listEvaluationRuns,
    staleTime: STALE_MS,
  });
}

export function useLatestEvaluation() {
  return useQuery({
    queryKey: evaluationKeys.latest(),
    queryFn: latestEvaluation,
    staleTime: STALE_MS,
  });
}

/**
 * One run by id, for the picker. Disabled until a run is chosen, so the screen
 * opens on `useLatestEvaluation` without asking for a second report it would
 * throw away.
 */
export function useEvaluationReport(runId: string | null) {
  return useQuery({
    queryKey: evaluationKeys.report(runId ?? ''),
    queryFn: () => getEvaluation(runId as string),
    enabled: runId !== null,
    staleTime: STALE_MS,
  });
}
