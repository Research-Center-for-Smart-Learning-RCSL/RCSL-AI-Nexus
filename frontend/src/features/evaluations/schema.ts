import { z } from 'zod';

/**
 * A stored capability evaluation, as the admin API serves it.
 *
 * Mirrors `domain/entities/evaluation.py`. The shapes are checked against the
 * generated API types in `lib/api-contract.ts`, and parsed at runtime here, for
 * the reason that file gives: the generated types are erased, and a deployment
 * serving something its own schema does not describe should produce one legible
 * error rather than `undefined` spreading through a table.
 */

/**
 * What one task did to the field of models in a run.
 *
 * A closed union rather than `string`, because the screen renders each of these
 * differently and a value it does not know would render as nothing at all. The
 * backend's enum is the definition; this is the copy the parser enforces.
 */
export const taskVerdictSchema = z.enum([
  'discriminates',
  'saturated_high',
  'saturated_low',
  'undecided',
]);
export type TaskVerdict = z.infer<typeof taskVerdictSchema>;

/**
 * What each verdict means, for a reader who did not design the task set.
 *
 * The distinction the evaluation rests on: a task every model passes and a task
 * every model fails both produce a tidy column and neither separates anybody.
 * Without these sentences a reader counts eighteen tasks and believes eighteen
 * of them contributed to the ranking.
 */
export const VERDICT_LABELS: Record<TaskVerdict, string> = {
  discriminates: 'Separates the models',
  saturated_high: 'Every model passed',
  saturated_low: 'Every model failed',
  undecided: 'No clear separation',
};

export const VERDICT_DESCRIPTIONS: Record<TaskVerdict, string> = {
  discriminates:
    'The scores are far enough apart to distinguish the models. The comparison rests on these tasks and on no others.',
  saturated_high:
    'Every model scored full marks, so this task contributed nothing to the comparison.',
  saturated_low:
    'Every model scored zero. That is a finding about the task, or about the whole field, and never about one model.',
  undecided:
    'Scored, but the models are too close together for the result to separate them.',
};

export const evaluationRunSchema = z.object({
  id: z.string(),
  label: z.string(),
  phase: z.string(),
  ran_at: z.string(),
  harness_ref: z.string(),
  sample_count: z.number(),
  /** What the run does not establish, in the words of whoever ran it. */
  caveats: z.array(z.string()),
  note: z.string(),
  imported_at: z.string().nullable(),
  imported_by: z.string().nullable(),
});
export type EvaluationRun = z.infer<typeof evaluationRunSchema>;

export const evaluationRunListSchema = z.array(evaluationRunSchema);

export const evaluationModelScoreSchema = z.object({
  model_ref: z.string(),
  /** 0..1, or null when nothing scored. */
  score: z.number().nullable(),
  scored_samples: z.number(),
  no_result_samples: z.number(),
  generation_tokens_per_second: z.number().nullable(),
  prompt_depth_tokens: z.number().nullable(),
  seconds_per_round_min: z.number().nullable(),
  seconds_per_round_max: z.number().nullable(),
});
export type EvaluationModelScore = z.infer<typeof evaluationModelScoreSchema>;

export const evaluationTaskScoreSchema = z.object({
  model_ref: z.string(),
  task: z.string(),
  group: z.string(),
  score: z.number().nullable(),
  samples: z.number(),
});
export type EvaluationTaskScore = z.infer<typeof evaluationTaskScoreSchema>;

/**
 * The text of one task, as the run asked it.
 *
 * Stored with the run rather than read from the harness, because a task's
 * wording changes: `vm_trace` was shortened between two phases on 2026-09-03
 * when its original length was found to be measuring the output budget rather
 * than the model. Pairing a stored score with today's wording would show a
 * question that run never asked.
 */
export const evaluationTaskDefinitionSchema = z.object({
  task: z.string(),
  group: z.string(),
  kind: z.string(),
  prompt: z.string(),
  /** Independent scoring units. A code task's checks, a dialogue's per-turn
   * assertions, or 1 for a single exact answer — which is what makes a 0.62
   * on one task and a 0.62 on another mean different amounts of evidence. */
  checks: z.number(),
});
export type EvaluationTaskDefinition = z.infer<typeof evaluationTaskDefinitionSchema>;

export const evaluationReportSchema = z.object({
  run: evaluationRunSchema,
  models: z.array(evaluationModelScoreSchema),
  tasks: z.array(evaluationTaskScoreSchema),
  /**
   * Defaulted, and that is not defensive coding. Runs imported before the text
   * was stored are still on the screen and still correct; they simply cannot
   * show their questions, and the table has to render them rather than fail.
   */
  task_definitions: z.array(evaluationTaskDefinitionSchema).default([]),
  /**
   * Task name to verdict, computed by the backend over the whole field of
   * models. Deliberately not derived in the browser: a screen computing it from
   * the rows it happens to have rendered would get it wrong the moment a filter
   * existed.
   */
  verdicts: z.record(z.string(), taskVerdictSchema),
});
export type EvaluationReport = z.infer<typeof evaluationReportSchema>;

/** `null` on a deployment that has never run the task set, which is normal. */
export const latestEvaluationSchema = evaluationReportSchema.nullable();

/** A short label for a model: the tag after the colon, or the family if none. */
export function shortModelLabel(modelRef: string): string {
  const colon = modelRef.indexOf(':');
  return colon >= 0 ? modelRef.slice(colon + 1) : modelRef;
}

/** Tasks grouped by their group letter, in the order they appear. */
export function tasksByGroup(report: EvaluationReport): { group: string; tasks: { task: string; group: string }[] }[] {
  const order = taskOrder(report);
  const groups: { group: string; tasks: { task: string; group: string }[] }[] = [];
  let current: typeof groups[0] | null = null;
  for (const entry of order) {
    if (!current || current.group !== entry.group) {
      current = { group: entry.group, tasks: [] };
      groups.push(current);
    }
    current.tasks.push(entry);
  }
  return groups;
}

/** A percentage, or an em dash where there is no score to show. */
export function formatScore(score: number | null): string {
  return score === null ? '—' : `${(score * 100).toFixed(1)}%`;
}

export function formatRate(rate: number | null): string {
  return rate === null ? '—' : `${rate.toFixed(1)} tok/s`;
}

/**
 * The wall clock for one pass over the task set, as a range.
 *
 * Collapsed to a single figure when the rounds agree to the second, because
 * "246–246 s" reads as a rendering fault rather than as a stable measurement.
 */
export function formatRoundSeconds(
  min: number | null,
  max: number | null,
): string {
  if (min === null || max === null) return '—';
  if (Math.round(min) === Math.round(max)) return `${Math.round(min)} s`;
  return `${Math.round(min)}–${Math.round(max)} s`;
}

/**
 * The key one cell of the grid is stored under.
 *
 * Exported so the index and every lookup are built by the same function. Two
 * call sites composing the same string by hand is how a grid ends up rendering
 * a column of blanks against data that is present.
 *
 * The separator is a newline because neither half can contain one: a task is an
 * identifier and a model reference is a registry string, while a space appears
 * in neither but is easy to get wrong by one character.
 */
export function taskKey(task: string, modelRef: string): string {
  return `${task}\n${modelRef}`;
}

/**
 * The scores of one run, indexed for a grid.
 *
 * Built once per report rather than searched per cell: the table is tasks by
 * models, so a linear scan per cell turns a run of eighteen tasks and three
 * models into nine hundred passes over the same array.
 */
export function indexTaskScores(
  report: EvaluationReport,
): Map<string, EvaluationTaskScore> {
  return new Map(
    report.tasks.map((entry) => [taskKey(entry.task, entry.model_ref), entry]),
  );
}

/** The task text of a run, indexed by task id. Empty for a run imported before
 * the text was stored, which the table renders as a row with nothing to open. */
export function indexTaskDefinitions(
  report: EvaluationReport,
): Map<string, EvaluationTaskDefinition> {
  return new Map(report.task_definitions.map((entry) => [entry.task, entry]));
}

/** The tasks of a run, in the order the harness emitted them. */
export function taskOrder(report: EvaluationReport): { task: string; group: string }[] {
  const seen = new Set<string>();
  const order: { task: string; group: string }[] = [];
  for (const entry of report.tasks) {
    if (seen.has(entry.task)) continue;
    seen.add(entry.task);
    order.push({ task: entry.task, group: entry.group });
  }
  return order;
}

/**
 * How many tasks fall under each verdict.
 *
 * The headline the run's own record leads with — eleven of eighteen carrying no
 * signal is the sentence that decides how much the ranking above it is worth —
 * so it is computed rather than left for the reader to count.
 */
export function countVerdicts(report: EvaluationReport): Record<TaskVerdict, number> {
  const counts: Record<TaskVerdict, number> = {
    discriminates: 0,
    saturated_high: 0,
    saturated_low: 0,
    undecided: 0,
  };
  for (const verdict of Object.values(report.verdicts)) counts[verdict] += 1;
  return counts;
}
