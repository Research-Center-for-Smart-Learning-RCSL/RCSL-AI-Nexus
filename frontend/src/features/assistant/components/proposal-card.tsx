'use client';

/**
 * A set of suggested values, and a button that puts them in the form.
 *
 * Every field the proposal names is listed, because applying it is the point at
 * which the operator stops reading and starts trusting. A card that said only
 * "apply these settings" would be asking for that trust without showing what is
 * being changed, and the assistant is a language model — the reason this is a
 * card rather than an action is precisely that a person should look first.
 *
 * Applying fills the form. It does not save: the existing dialog still performs
 * the write, with the scope check and the audit record it has always had.
 */

import { CheckIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  proposalToFormPatch,
  type Proposal,
} from '@/features/assistant/schema';

const LABELS: Record<string, string> = {
  name: 'Name',
  scopes: 'Capabilities',
  rate_limit_rpm: 'Rate limit (rpm)',
  quota_tokens_per_day: 'Daily token quota',
  allowed_cidrs: 'Allowed source CIDRs',
  expires_at: 'Expires',
};

function describe(field: string, value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'none';
  // Shown as the day it will become, because that is what applying it writes:
  // the API and the form's date input both take `YYYY-MM-DD`, and
  // `proposalToFormPatch` truncates the proposal's timestamp to one. Printing
  // the instant would describe something other than what the button does.
  if (field === 'expires_at' && typeof value === 'string') {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) return date.toISOString().slice(0, 10);
  }
  return String(value);
}

export function ProposalCard({
  proposal,
  canApply,
  onApply,
}: {
  proposal: Proposal;
  canApply: boolean;
  onApply: (proposal: Proposal) => void;
}) {
  const entries = Object.entries(proposal.fields);

  return (
    <div className="mt-2 space-y-2 rounded-lg border border-foreground/15 bg-muted/40 p-3">
      <p className="text-xs font-medium text-muted-foreground">
        Suggested settings
      </p>

      <dl className="space-y-1 text-sm">
        {entries.map(([field, value]) => (
          <div key={field} className="flex gap-2">
            <dt className="shrink-0 text-muted-foreground">
              {LABELS[field] ?? field}
            </dt>
            <dd className="break-all">{describe(field, value)}</dd>
          </div>
        ))}
      </dl>

      <p className="text-xs text-muted-foreground">{proposal.rationale}</p>

      {canApply ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onApply(proposal)}
        >
          <CheckIcon className="size-3.5" />
          Fill the form
        </Button>
      ) : (
        // The usual case for this branch is a proposal that arrived after the
        // dialog was closed. Saying so beats a disabled button with no reason,
        // and the values above are still readable and still correct.
        <p className="text-xs text-muted-foreground">
          Open the key form to apply these.
        </p>
      )}
    </div>
  );
}

export { proposalToFormPatch };
