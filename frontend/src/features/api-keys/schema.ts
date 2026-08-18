import { z } from 'zod';

import {
  issuableCapabilitySchema,
  type IssuableCapability,
} from '@/features/models/schema';

/**
 * Mirrors security.md section 4.2. The plaintext key is never stored and is
 * returned exactly once, at issue; `key_id` is the lookup handle that is safe
 * to show in the UI and in logs because it reveals nothing about the secret.
 */

export const apiKeySchema = z.object({
  key_id: z.string(),
  name: z.string(),
  scopes: z.array(issuableCapabilitySchema),
  rate_limit_rpm: z.number().int().nonnegative(),
  quota_tokens_per_day: z.number().int().nonnegative(),
  allowed_cidrs: z.array(z.string()),
  expires_at: z.string(),
  owner_id: z.string(),
  owner_display: z.string().nullable(),
  revoked_at: z.string().nullable(),
  /** Nullable for the reason `User.created_at` is: the column is `NOT NULL`,
   *  but an entity built and not yet read back has no timestamp, and the issue
   *  response is exactly such a path. */
  created_at: z.string().nullable(),
  last_used_at: z.string().nullable(),
  /** Served when a request names a capability this key was not issued for;
   *  null refuses, which is the default and what every key did before the
   *  field existed. Always one of `scopes`, which is what makes it a shortcut
   *  rather than a grant.
   *
   *  A plain string rather than the capability enum on purpose: the server
   *  constrains the value, and a row that somehow held something else should
   *  make the gateway refuse it — which it does — rather than make this screen
   *  fail to parse and show an administrator nothing at all. */
  default_capability: z.string().nullable(),
  debug_logging_until: z.string().nullable(),
  /** While this is in the future, error responses to this key carry the
   * operator-facing detail that is otherwise log-only. Set from the table's
   * debug action; the backend caps the window at 24 hours. */
});
export type ApiKey = z.infer<typeof apiKeySchema>;

export const apiKeyListSchema = z.array(apiKeySchema);

/** IPv4 or IPv6 with a prefix length. The server re-validates. */
const CIDR_PATTERN = /^([0-9.]+|[0-9a-fA-F:]+)\/\d{1,3}$/;

/**
 * The textarea holds one string; the request takes a list. Splitting lives
 * here so that validation and submission split identically. Validating an
 * array the form never holds, and building the one that is sent separately at
 * submit, is how a rule can pass while never having seen the input.
 */
export function parseCidrText(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

/** Validated as the text the field actually holds, so the message lands on it. */
export const cidrTextSchema = z
  .string()
  .refine(
    (text) => parseCidrText(text).every((entry) => CIDR_PATTERN.test(entry)),
    'Expected addresses with a prefix, for example 203.0.113.0/24.',
  );

/**
 * What the select holds for "no default", and why it is a word.
 *
 * The wire value is `null` and the obvious form value would be `''`, but an
 * empty string is the one value a select cannot distinguish from "nothing
 * chosen yet" — it renders the placeholder, so the setting most keys should
 * have would be the one the control refuses to show. A named option says
 * out loud what happens.
 */
export const NO_DEFAULT = 'refuse';

/** The select's sentinel back to what the request carries. */
export function defaultCapabilityPayload(value: string): string | null {
  return value === NO_DEFAULT ? null : value;
}

/** And back again, for a form opened on a stored key. */
export function defaultCapabilityField(value: string | null): string {
  return value ?? NO_DEFAULT;
}

/**
 * Which capabilities the default select offers: the ones ticked, plus whatever
 * the field already holds.
 *
 * The second half is not tidiness. Unticking the capability a default names is
 * refused rather than silently cleared, so that state is reachable and
 * expected — and a Select whose value matches none of its items renders its
 * trigger blank, which would leave the operator being told to fix a field that
 * was showing them nothing.
 */
export function defaultCapabilityOptions(
  scopes: IssuableCapability[],
  current: string,
): string[] {
  if (current === NO_DEFAULT || current === '') return scopes;
  return scopes.includes(current as IssuableCapability)
    ? scopes
    : [...scopes, current];
}

/**
 * The default must be one of the capabilities being granted in the same form.
 *
 * Checked here as well as on the server because the server's refusal is a 409
 * on a request that also carried the capability edit, and a form that can only
 * learn this by being rejected makes the operator guess which half was wrong.
 * The rule itself lives in `ManageApiKeys`; this is the same rule stated where
 * it can land on the field.
 */
function defaultWithinScopes<
  T extends { scopes: IssuableCapability[]; default_capability: string },
>(values: T, ctx: z.RefinementCtx): void {
  if (values.default_capability === NO_DEFAULT) return;
  if (values.scopes.includes(values.default_capability as IssuableCapability)) {
    return;
  }
  ctx.addIssue({
    code: 'custom',
    path: ['default_capability'],
    message: 'Choose a capability this key is being issued for.',
  });
}

export const createApiKeySchema = z
  .object({
    name: z.string().min(1, 'Required').max(80),
    scopes: z
      .array(issuableCapabilitySchema)
      .min(1, 'Choose at least one capability.'),
    rate_limit_rpm: z.coerce.number().int().positive(),
    quota_tokens_per_day: z.coerce.number().int().positive(),
    allowed_cidrs_text: cidrTextSchema,
    // Expiry is mandatory by design: it forces rotation. There is no "never".
    expires_at: z.string().min(1, 'An expiry is required.'),
    owner_id: z.string().min(1, 'Required'),
    /** Defaulted rather than required, so the safe answer is what an input
     *  missing the field parses to. `NO_DEFAULT` is "refuse". */
    default_capability: z.string().default(NO_DEFAULT),
  })
  .superRefine(defaultWithinScopes);
/**
 * Input and output types differ here and must be kept apart: `z.coerce`
 * accepts the string a number input actually produces, so `z.infer` (the
 * output type) would claim the form holds numbers it only holds after
 * parsing. react-hook-form takes both, which keeps the resolver assignable.
 */
export type CreateApiKeyInput = z.input<typeof createApiKeySchema>;
export type CreateApiKeyValues = z.output<typeof createApiKeySchema>;

/** The request body: the form's values with the CIDR text split. */
export type CreateApiKeyPayload = {
  name: string;
  owner_id: string;
  scopes: IssuableCapability[];
  rate_limit_rpm: number;
  quota_tokens_per_day: number;
  allowed_cidrs: string[];
  expires_at: string;
  default_capability: string | null;
};

/**
 * Mirrors `UpdateApiKeyRequest`. `owner_id` is deliberately absent: the
 * backend checks permission against the key's *current* owner, so an edit can
 * only ever leave a key where it is, and offering the field would promise a
 * transfer that does not exist.
 */
export const updateApiKeySchema = z
  .object({
    name: z.string().min(1, 'Required').max(80),
    scopes: z
      .array(issuableCapabilitySchema)
      .min(1, 'Choose at least one capability.'),
    rate_limit_rpm: z.coerce.number().int().positive(),
    quota_tokens_per_day: z.coerce.number().int().positive(),
    allowed_cidrs_text: cidrTextSchema,
    expires_at: z.string().min(1, 'An expiry is required.'),
    default_capability: z.string().default(NO_DEFAULT),
  })
  .superRefine(defaultWithinScopes);
/** Input and output differ for the same reason they do on create. */
export type UpdateApiKeyInput = z.input<typeof updateApiKeySchema>;
export type UpdateApiKeyValues = z.output<typeof updateApiKeySchema>;

/**
 * The request body. It is the form's values with the CIDR text split, which
 * is why it is a separate type rather than the schema's output.
 */
export type UpdateApiKeyPayload = {
  name: string;
  scopes: IssuableCapability[];
  rate_limit_rpm: number;
  quota_tokens_per_day: number;
  allowed_cidrs: string[];
  expires_at: string;
  /** Always sent, and `null` clears rather than meaning "unchanged" — the one
   *  field on this verb where the server tells absence and null apart. */
  default_capability: string | null;
};

/** Issue response. `plaintext` exists here and nowhere else, ever. */
export const issuedApiKeySchema = z.object({
  key: apiKeySchema,
  plaintext: z.string(),
});
export type IssuedApiKey = z.infer<typeof issuedApiKeySchema>;

export const DEFAULT_EXPIRY_DAYS = 90;

export function defaultExpiry(): string {
  const date = new Date();
  date.setDate(date.getDate() + DEFAULT_EXPIRY_DAYS);
  return date.toISOString().slice(0, 10);
}

export function keyStatus(key: ApiKey): 'active' | 'revoked' | 'expired' {
  if (key.revoked_at) return 'revoked';
  if (new Date(key.expires_at).getTime() <= Date.now()) return 'expired';
  return 'active';
}

/**
 * `<input type="date">` accepts only `YYYY-MM-DD`, while the API sends a full
 * timestamp. Returns empty for an unparsable value so the field is blank and
 * the required rule fires, rather than silently holding something the input
 * will not display.
 */
export function toDateInput(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toISOString().slice(0, 10);
}

/**
 * Mirrors `_require_owner_permission` in `manage_api_keys.py`: your own key
 * needs `api_key:write_own`, which every role holds; anyone else's needs
 * `api_key:write_any`, which only an administrator holds.
 *
 * Role gating in the UI is an affordance, not a control — the server checks
 * the same thing and is the one that decides. What it buys is that a member
 * is offered the actions they can actually complete, which is the whole of
 * what §5.2 grants them: managing their own keys.
 */
export function canManageKey(
  key: ApiKey,
  viewer: { id: string | null; mayWriteAny: boolean; mayWriteOwn: boolean },
): boolean {
  // `api_key:write_any` rather than "is an administrator". They were the same
  // question while `admin` was the only role holding that scope; `tenant_admin`
  // now holds it too, and `operator` deliberately does not — an operator who
  // can issue a key for somebody else can hand themselves the gateway.
  if (viewer.mayWriteAny) return true;
  // Owning a row is no longer enough on its own. `auditor` holds no write at
  // all, not even `api_key:write_own`, so its own keys are listed and Rotate
  // and Revoke are refused — the whole point of the role is that it leaves
  // only a read behind.
  return viewer.mayWriteOwn && viewer.id !== null && key.owner_id === viewer.id;
}
