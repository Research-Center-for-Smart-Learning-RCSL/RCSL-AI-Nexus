import type { Metadata } from 'next';

import { NodeTable } from '@/features/nodes/components/node-table';

export const metadata: Metadata = { title: 'Nodes' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function NodesPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Nodes</h1>
        <p className="text-sm text-muted-foreground">
          Compute nodes that run the model runtimes. Status is observed by a
          periodic health probe; the address is validated against the tailnet
          range before it is stored.
        </p>
      </div>
      <NodeTable />
    </div>
  );
}
