import { describe, expect, it } from 'vitest';

import {
  countVerdicts,
  evaluationReportSchema,
  formatRoundSeconds,
  formatScore,
  indexTaskScores,
  taskKey,
  taskOrder,
  type EvaluationReport,
} from '@/features/evaluations/schema';

/**
 * The parts of this feature that are logic rather than layout.
 *
 * The grid is the one worth pinning: it is built from two independent lists —
 * models and task scores — and the failure mode is not an exception but a row
 * whose cells belong to the model in the next column.
 */

function report(overrides: Partial<EvaluationReport> = {}): EvaluationReport {
  return {
    run: {
      id: 'r1',
      label: 'a run',
      phase: 'full',
      ran_at: '2026-08-15T12:00:00Z',
      harness_ref: 'scripts/model-eval',
      sample_count: 4,
      caveats: [],
      note: '',
      imported_at: null,
      imported_by: null,
    },
    models: [],
    tasks: [],
    verdicts: {},
    ...overrides,
  };
}

function task(model: string, name: string, score: number | null) {
  return { model_ref: model, task: name, group: 'A', score, samples: 1 };
}

describe('the task grid', () => {
  it('indexes a score by task and model together', () => {
    const scores = indexTaskScores(
      report({
        tasks: [task('m1', 't1', 1), task('m2', 't1', 0), task('m1', 't2', 0.5)],
      }),
    );

    expect(scores.get(taskKey('t1', 'm1'))?.score).toBe(1);
    expect(scores.get(taskKey('t1', 'm2'))?.score).toBe(0);
    expect(scores.get(taskKey('t2', 'm1'))?.score).toBe(0.5);
  });

  it('keeps the order the harness emitted rather than sorting', () => {
    // The task set is meant to be read in its own order and the groups mean
    // something in it. Sorting here would silently reorder every row.
    const order = taskOrder(
      report({ tasks: [task('m1', 'zulu', 1), task('m1', 'alpha', 1)] }),
    );

    expect(order.map((entry) => entry.task)).toEqual(['zulu', 'alpha']);
  });

  it('lists a task once however many models attempted it', () => {
    const order = taskOrder(
      report({ tasks: [task('m1', 't1', 1), task('m2', 't1', 1)] }),
    );

    expect(order).toHaveLength(1);
  });
});

describe('the verdict counts', () => {
  it('counts every verdict, including the ones with none', () => {
    // Rendered as a legend with a number beside each, so a missing key would
    // render `undefined` rather than a zero.
    const counts = countVerdicts(
      report({
        verdicts: { a: 'discriminates', b: 'saturated_high', c: 'saturated_high' },
      }),
    );

    expect(counts).toEqual({
      discriminates: 1,
      saturated_high: 2,
      saturated_low: 0,
      undecided: 0,
    });
  });
});

describe('formatting', () => {
  it('shows an em dash rather than a zero where there is no score', () => {
    // `0%` and "not measured" are different statements, and this table carries
    // both: a task every model failed really is zero.
    expect(formatScore(null)).toBe('—');
    expect(formatScore(0)).toBe('0.0%');
    expect(formatScore(0.944)).toBe('94.4%');
  });

  it('collapses a round range whose ends agree', () => {
    // "246–246 s" reads as a rendering fault rather than as a stable
    // measurement.
    expect(formatRoundSeconds(246.2, 246.4)).toBe('246 s');
    expect(formatRoundSeconds(246, 285)).toBe('246–285 s');
    expect(formatRoundSeconds(null, 285)).toBe('—');
  });
});

describe('parsing', () => {
  it('refuses a verdict this build does not know', () => {
    // The union is closed because the screen renders each value differently,
    // and one it does not know would render as nothing at all.
    const parsed = evaluationReportSchema.safeParse({
      ...report(),
      verdicts: { t1: 'brilliant' },
    });

    expect(parsed.success).toBe(false);
  });

  it('accepts a null score, which is a sample that returned no result', () => {
    const parsed = evaluationReportSchema.safeParse({
      ...report({ tasks: [task('m1', 't1', null)] }),
    });

    expect(parsed.success).toBe(true);
  });
});
