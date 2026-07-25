import type { Metadata } from 'next';

import { ModelTable } from '@/features/models/components/model-table';

export const metadata: Metadata = { title: 'Models' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function ModelsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Models</h1>
        <p className="text-sm text-muted-foreground">
          Routing policies bind to the alias, so swapping the underlying model
          does not mean editing every policy.
        </p>
      </div>
      <ModelTable />
    </div>
  );
}
