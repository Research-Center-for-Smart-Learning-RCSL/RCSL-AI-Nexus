import type { Metadata } from 'next';

import { HostStatusCard } from '@/features/host/components/host-status-card';
import { RelatedScreens } from '@/components/composed/related-screens';
import { NodeTable } from '@/features/nodes/components/node-table';

export const metadata: Metadata = { title: 'Nodes' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function NodesPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Nodes</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          The machines that run the model runtimes and hold loaded weights in
          memory. Each node records a private network address and a total
          memory figure; the address must be on the tailnet, and the memory
          figure must match the real machine, because it is what the load check
          budgets against — set it too high and loads are permitted that push
          the host into swap.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Status is observed by a periodic probe rather than declared, so a node
          that stops answering is marked offline without anyone editing it, and
          routing requirements that ask for an online node stop selecting it.
          The panel below reports the capacity currently free on the compute
          host, which is the figure to check before loading a model.
        </p>
      </div>
      {/* Above the table: what the machine has left is the thing an operator
          came to check before loading a model, and the registry row underneath
          says what is loaded rather than whether there is room for more. */}
      <HostStatusCard />
      <NodeTable />
      <RelatedScreens
        items={[
          {
            href: '/models',
            label: 'Models',
            requires: 'model:read',
            note: 'every model names the node it runs on, and its declared memory is checked against this node\u2019s total before a load is allowed',
          },
          {
            href: '/routing-policies',
            label: 'Routing policies',
            requires: 'routing:read',
            note: 'a candidate can require an online node or a minimum of free memory, so what this screen observes decides what that screen selects',
          },
        ]}
      />
    </div>
  );
}
