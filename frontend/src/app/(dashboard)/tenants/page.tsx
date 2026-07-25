import type { Metadata } from 'next';

import { TenantTable } from '@/features/tenants/components/tenant-table';

export const metadata: Metadata = { title: 'Tenants' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function TenantsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Tenants</h1>
        <p className="text-sm text-muted-foreground">
          The isolation boundary for users, API keys and usage. Each account
          belongs to exactly one tenant; shared infrastructure (models, nodes,
          routing) is common to all.
        </p>
      </div>
      <TenantTable />
    </div>
  );
}
