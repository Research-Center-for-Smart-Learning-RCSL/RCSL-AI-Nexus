/**
 * What the two key dialogs publish to the assistant, and what they accept back.
 *
 * Shared rather than written twice. The create and edit forms hold the same
 * fields and would need the same two conversions, and the copy that drifted
 * would be the one nobody noticed: a draft missing a field simply produces
 * slightly worse advice, with nothing on screen to say why.
 *
 * **`draftFor` takes form values, not the dialog's state.** The create dialog
 * holds an issued key's plaintext at the same time as it holds these values,
 * and that plaintext must never leave the dialog. Passing the form's values
 * explicitly, into a parameter typed as the draft, means there is no call this
 * function could be given the secret through.
 */

import type { ApiKeyDraft } from '@/features/assistant/schema';
import type { FormPatch } from '@/features/assistant/context';
import type { IssuableCapability } from '@/features/models/schema';
import { parseCidrText } from '@/features/api-keys/schema';

/**
 * The fields a proposal is allowed to touch, and the only names passed to
 * `setValue`.
 *
 * An allowlist rather than a pass-through of whatever arrived. The patch is
 * derived from a language model's output, and while it has been schema-checked
 * twice by this point, `setValue` with an unrecognised name is a silent no-op
 * on a good day and a corrupted form state on a bad one. `owner_id` is absent
 * for the reason it is absent from every layer below: who holds a key is not a
 * setting.
 */
export const APPLICABLE_FIELDS = [
  'name',
  'scopes',
  'rate_limit_rpm',
  'quota_tokens_per_day',
  'allowed_cidrs_text',
  'expires_at',
] as const;

export type ApplicableField = (typeof APPLICABLE_FIELDS)[number];

/**
 * The shape both key forms hold. The two numeric fields are `unknown` because
 * that is genuinely what react-hook-form's input type says: `z.coerce` makes
 * the schema's input and output types differ, so before parsing these hold
 * whatever was typed. Stringified through `text` below rather than asserted.
 */
export type KeyFormValues = {
  name?: string;
  scopes?: IssuableCapability[];
  rate_limit_rpm?: unknown;
  quota_tokens_per_day?: unknown;
  allowed_cidrs_text?: string;
  expires_at?: string;
};

function text(value: unknown): string {
  if (value === null || value === undefined) return '';
  return typeof value === 'object' ? '' : String(value);
}

/**
 * The form's current values as the assistant's draft.
 *
 * Numbers are stringified because that is what the field actually holds before
 * `z.coerce` runs, and the draft is published precisely when the form does not
 * yet validate. `""` is sent as `""`: an empty rate limit is a fact worth
 * knowing, and dropping it would make an unfilled form indistinguishable from
 * one nobody has opened.
 */
export function draftFor(values: KeyFormValues): ApiKeyDraft {
  return {
    name: values.name ?? '',
    scopes: values.scopes ?? [],
    rate_limit_rpm: text(values.rate_limit_rpm),
    quota_tokens_per_day: text(values.quota_tokens_per_day),
    allowed_cidrs: parseCidrText(values.allowed_cidrs_text ?? ''),
    expires_at: values.expires_at ?? '',
  };
}

/**
 * Writes an accepted proposal into a form, one named field at a time.
 *
 * Takes a setter rather than the form itself, so the two dialogs keep their own
 * exact `useForm` types at the call site and this module needs no union of
 * them. Fields the proposal did not name are not touched: an omitted field must
 * leave what the operator typed alone.
 */
export function applyProposalPatch(
  patch: FormPatch,
  setField: (name: ApplicableField, value: string | string[]) => void,
): void {
  for (const field of APPLICABLE_FIELDS) {
    const value = patch[field];
    if (value !== undefined) setField(field, value);
  }
}
