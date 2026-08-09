import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { TenantTable } from '@/features/tenants/components/tenant-table';

export const metadata: Metadata = { title: 'Tenants' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function TenantsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Tenants</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          A tenant is a wall between groups using the same installation. Every
          account, key, uploaded document, prompt template and usage record
          belongs to exactly one, and nothing crosses: one tenant&apos;s
          questions are never answered from another&apos;s documents, and its
          administrators see only its own people and figures.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          <strong>The machines are shared.</strong> Models, nodes and routing
          are common to the whole installation, so tenants separate content and
          identity rather than capacity — they draw on the same hardware and the
          same limits. Use one per group that should not see another&apos;s
          material; a tenant is not a way to give one group more of the server.
        </p>
      </div>
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
