import type { Metadata } from 'next';

import { HostStatusCard } from '@/features/host/components/host-status-card';
import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { NodeTable } from '@/features/nodes/components/node-table';

export const metadata: Metadata = { title: 'Nodes' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function NodesPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Nodes"
        lead="The machines that run the model runtimes and hold loaded weights in memory."
      >
        <p>
          Each node records a private network address and a total memory figure.
          The address must be on the tailnet. The memory figure must correspond
          to the real machine, because it is what the load check budgets
          against: set above the true capacity, it permits loads that drive the
          host into swap.
        </p>
        <p>
          Status is observed by a periodic probe rather than declared, so a node
          that stops answering is marked offline without intervention, and
          routing requirements that specify an online node cease to select it.
          The panel below reports the capacity currently free on the compute
          host, which is the figure to consult before loading a model.
        </p>
      </PageHeader>
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
            note: 'every model names the node it runs on, and its declared memory is checked against this node’s total before a load is permitted',
          },
          {
            href: '/routing-policies',
            label: 'Routing policies',
            requires: 'routing:read',
            note: 'a candidate can require an online node or a minimum of free memory, so what this screen observes determines what that screen selects',
          },
        ]}
      />
    </div>
  );
}
