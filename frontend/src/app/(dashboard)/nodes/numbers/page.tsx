import type { Metadata } from 'next';

import { HostNumbersExplainer } from '@/features/host/components/host-numbers-explainer';

export const metadata: Metadata = { title: 'Where these numbers come from' };

/**
 * A child route of Nodes rather than a nav entry: it is read once, from the
 * panel it explains, and a permanent sidebar item for it would cost every
 * operator a line of navigation for a page they need on their first day only.
 *
 * Thin by design (frontend.md section 2).
 */
export default function HostNumbersPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">
          Where these numbers come from
        </h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          The compute host panel, figure by figure — what each one is measured
          from, which one is derived and why, and what is deliberately not
          shown.
        </p>
      </div>
      <HostNumbersExplainer />
    </div>
  );
}
