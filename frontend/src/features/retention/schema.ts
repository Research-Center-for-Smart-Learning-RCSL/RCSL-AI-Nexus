import { z } from 'zod';

/**
 * How long records are kept, and what a purge would remove.
 *
 * Three datasets, and the set is closed on the server: the enum is the
 * allowlist, because these values reach a `DELETE`. The screen renders whatever
 * the server lists rather than a hardcoded set, so a fourth dataset appears
 * here without a frontend change — but it cannot invent one.
 *
 * **The bound is not the same shape for every dataset.** `audit_log` and
 * `usage_records` carry a floor: the danger there is forgetting too soon, and
 * an administrator may keep them as long as they like. `prompt_logs` carries a
 * *ceiling* instead. It holds message content, it exists only for the length of
 * a debugging session, and the failure the whole control was designed against
 * is full logging switched on for an afternoon and left on for a year.
 */

export const RETENTION_DATASETS = ['audit_log', 'usage_records', 'prompt_logs'] as const;
export type RetentionDataset = (typeof RETENTION_DATASETS)[number];

/**
 * What each dataset is, for someone deciding how long to keep it. The names
 * are table names, which is right for precision and useless for a decision.
 */
export const DATASET_LABELS: Record<RetentionDataset, string> = {
  audit_log: 'Audit log',
  usage_records: 'Usage records',
  prompt_logs: 'Prompt transcripts',
};

export const DATASET_DESCRIPTIONS: Record<RetentionDataset, string> = {
  audit_log:
    'Who did what: sign-ins, refusals, and every administrative action. Deleting these removes the record of what was done, including the record of this deletion.',
  usage_records:
    'What each request cost, per capability and per account. Quotas are measured against these, so a window shorter than the longest quota period would make enforcement wrong rather than merely forgetful.',
  prompt_logs:
    'The full prompt and completion text captured while a debug window was open: what researchers typed, and what the models answered. The most sensitive data the platform holds, and the only one here whose limit is a maximum rather than a minimum.',
};

export const MINIMUM_RETENTION_DAYS = 30;
/** Mirrors the server's floor so the form can say no before the request does.
 *  The server enforces it regardless; this only saves a round trip. */

export const PROMPT_LOG_MINIMUM_DAYS = 1;
export const PROMPT_LOG_MAXIMUM_DAYS = 30;

export type RetentionBounds = { min: number; max: number | null };

/**
 * The bounds per dataset, mirroring `domain/entities/retention.py`.
 *
 * A table rather than one constant, because the two shapes are opposite and a
 * single `MINIMUM_RETENTION_DAYS` applied to all three would put a floor of 30
 * on a dataset whose *ceiling* is 30 — refusing every value it accepts, and
 * doing so in the form rather than at the server, so nothing would reach the
 * error that explains it.
 */
export const RETENTION_BOUNDS: Record<RetentionDataset, RetentionBounds> = {
  audit_log: { min: MINIMUM_RETENTION_DAYS, max: null },
  usage_records: { min: MINIMUM_RETENTION_DAYS, max: null },
  prompt_logs: { min: PROMPT_LOG_MINIMUM_DAYS, max: PROMPT_LOG_MAXIMUM_DAYS },
};

export const retentionPolicySchema = z.object({
  dataset: z.enum(RETENTION_DATASETS),
  days: z.number().int().positive(),
  updated_at: z.string().nullable(),
  updated_by: z.string().nullable(),
});
export type RetentionPolicy = z.infer<typeof retentionPolicySchema>;

export const retentionPolicyListSchema = z.array(retentionPolicySchema);

export const retentionPreviewSchema = z.object({
  dataset: z.enum(RETENTION_DATASETS),
  days: z.number().int().positive(),
  affected: z.number().int().nonnegative(),
});
export type RetentionPreview = z.infer<typeof retentionPreviewSchema>;

export const purgeOutcomeSchema = z.object({
  dataset: z.enum(RETENTION_DATASETS),
  cutoff: z.string(),
  deleted: z.number().int().nonnegative(),
});
export type PurgeOutcome = z.infer<typeof purgeOutcomeSchema>;
