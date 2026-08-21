import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { TenantTable } from '@/features/tenants/components/tenant-table';

export const metadata: Metadata = { title: 'Tenants' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function TenantsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Tenants"
        lead="The boundary between groups sharing one installation."
      >
        <p>
          Every account, key, uploaded document, prompt template and usage
          record belongs to exactly one tenant, and nothing crosses the
          boundary: one tenant&apos;s questions are never answered from
          another&apos;s documents, and its administrators see only its own
          accounts and figures.
        </p>
        <p>
          <strong>The machines are shared.</strong> Models, nodes and routing
          are common to the whole installation, so tenants separate content and
          identity rather than capacity: they draw on the same hardware and the
          same limits. Create one per group that should not see another&apos;s
          material. A tenant is not a means of allocating a greater share of the
          server.
        </p>
      </PageHeader>
      <TenantTable />
      <RelatedScreens
        items={[
          {
            href: '/users',
            label: 'Users',
            requires: 'user:read',
            note: 'where an account is placed in a tenant, which is decided when it is invited',
          },
          {
            href: '/usage',
            label: 'Usage',
            note: 'consumption, counted within the boundary this screen defines',
          },
        ]}
      />
    </div>
  );
}
