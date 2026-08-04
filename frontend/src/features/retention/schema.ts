import { z } from 'zod';

/**
 * How long records are kept, and what a purge would remove.
 *
 * Two datasets, and the set is closed on the server: the enum is the allowlist,
 * because these values reach a `DELETE`. The screen renders whatever the server
 * lists rather than a hardcoded pair, so a third dataset appears here without a
 * frontend change — but it cannot invent one.
 */

export const RETENTION_DATASETS = ['audit_log', 'usage_records'] as const;
export type RetentionDataset = (typeof RETENTION_DATASETS)[number];

/**
 * What each dataset is, for someone deciding how long to keep it. The names
 * are table names, which is right for precision and useless for a decision.
 */
export const DATASET_LABELS: Record<RetentionDataset, string> = {
  audit_log: 'Audit log',
  usage_records: 'Usage records',
};

export const DATASET_DESCRIPTIONS: Record<RetentionDataset, string> = {
  audit_log:
    'Who did what: sign-ins, refusals, and every administrative action. Deleting these removes the record of what was done, including the record of this deletion.',
  usage_records:
    'What each request cost, per capability and per account. Quotas are measured against these, so a window shorter than the longest quota period would make enforcement wrong rather than merely forgetful.',
};

export const MINIMUM_RETENTION_DAYS = 30;
/** Mirrors the server's floor so the form can say no before the request does.
 *  The server enforces it regardless; this only saves a round trip. */

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
