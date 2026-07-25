import type { Metadata } from 'next';

import { PolicyTable } from '@/features/routing-policies/components/policy-table';

export const metadata: Metadata = { title: 'Routing policies' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function RoutingPoliciesPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Routing policies</h1>
        <p className="text-sm text-muted-foreground">
          Each capability resolves to the highest-priority candidate whose
          requirements hold. This is the one thing that makes the gateway serve
          anything.
        </p>
      </div>
      <PolicyTable />
    </div>
  );
}
