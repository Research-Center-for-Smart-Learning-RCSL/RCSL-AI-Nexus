import { z } from 'zod';

/**
 * How long records are kept, and what a purge would remove.
 *
 * **The bounds come from the server with each policy, and used to be mirrored
 * here.** That mirror broke this screen: `refusals` was added on 2026-08-18 as
 * a fourth dataset, and the frontend had a closed enum of three — so every
 * policy failed to parse behind the one unrecognised value and the page showed
 * nothing at all, under a docstring claiming a fourth dataset would appear
 * without a frontend change. Two tables that had to agree, in two languages,
 * with nothing failing until somebody opened the page.
 *
 * So the dataset is a plain string now and the bounds ride on the response.
 * What stays here is prose — a label and a sentence per dataset — because that
 * is a decision about how to explain something, not a fact about the schema,
 * and an unknown dataset falls back to its table name rather than to nothing.
 *
 * **The bound is not the same shape for every dataset.** `audit_log` and
 * `usage_records` carry a floor: the danger there is forgetting too soon, and
 * an administrator may keep them as long as they like. `prompt_logs` and
 * `refusals` carry a *ceiling* instead — one holds message content and exists
 * only for the length of a debugging session, and the other accumulates a
 * description of how somebody works.
 */

export type RetentionDataset = string;

/**
 * What each dataset is, for someone deciding how long to keep it. The names
 * are table names, which is right for precision and useless for a decision.
 */
export const DATASET_LABELS: Record<string, string> = {
  audit_log: 'Audit log',
  usage_records: 'Usage records',
  prompt_logs: 'Prompt transcripts',
  refusals: 'Refusals',
};

export const DATASET_DESCRIPTIONS: Record<string, string> = {
  audit_log:
    'Who did what: sign-ins, authorization denials, and every administrative action. Deleting these removes the record of what was done, including the record of this deletion.',
  usage_records:
    'What each request cost, per capability and per account. Quotas are measured against these, so a window shorter than the longest quota period would make enforcement wrong rather than merely forgetful.',
  prompt_logs:
    'The full prompt and completion text captured while a debug window was open: what researchers typed, and what the models answered. The most sensitive data the platform holds, and the only one here whose limit is a maximum rather than a minimum.',
  refusals:
    'Every request the platform turned away, with the message its caller was given and the figures that came with it. No request content, but a month of somebody’s refusals describes how they work — which is why this one has a ceiling as well as a floor.',
};

/** A dataset nobody has written prose for still has to render. */
export function datasetLabel(dataset: string): string {
  return DATASET_LABELS[dataset] ?? dataset.replace(/_/g, ' ');
}

export function datasetDescription(dataset: string): string {
  return (
    DATASET_DESCRIPTIONS[dataset] ??
    'No description has been written for this record type yet. The window below is the one the server enforces.'
  );
}

export type RetentionBounds = { min: number; max: number | null };

export const retentionPolicySchema = z.object({
  dataset: z.string(),
  days: z.number().int().positive(),
  updated_at: z.string().nullable(),
  updated_by: z.string().nullable(),
  minimum_days: z.number().int().positive(),
  maximum_days: z.number().int().positive().nullable(),
});
export type RetentionPolicy = z.infer<typeof retentionPolicySchema>;

export const retentionPolicyListSchema = z.array(retentionPolicySchema);

export const retentionPreviewSchema = z.object({
  dataset: z.string(),
  days: z.number().int().positive(),
  affected: z.number().int().nonnegative(),
});
export type RetentionPreview = z.infer<typeof retentionPreviewSchema>;

export const purgeOutcomeSchema = z.object({
  dataset: z.string(),
  cutoff: z.string(),
  deleted: z.number().int().nonnegative(),
});
export type PurgeOutcome = z.infer<typeof purgeOutcomeSchema>;
