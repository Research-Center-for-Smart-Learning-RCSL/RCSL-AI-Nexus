import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { ApiKeyTable } from '@/features/api-keys/components/api-key-table';

export const metadata: Metadata = { title: 'API keys' };

export default function ApiKeysPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="API keys"
        lead="Credentials that permit code and tools outside this deployment to call it."
      >
        <p>
          A key is <strong>displayed once, at creation</strong>. Only a one-way
          hash is stored, so a lost key is replaced rather than recovered.
        </p>
        <p>
          Each key is scoped to the capabilities it may request. Issue the
          narrowest set sufficient for the intended use: the value of a key to
          an unauthorised holder is the breadth of what it can reach.
        </p>
      </PageHeader>
      <ApiKeyTable />
      <RelatedScreens
        items={[
          {
            href: '/api-docs',
            label: 'API reference',
            note: 'where to send a key and what a request consists of, rendered from this deployment',
          },
          {
            href: '/agent-setup',
            label: 'Connect an agent',
            note: 'the same key configured in a coding agent, step by step, including the two limits whose defaults are unsuitable for that use',
          },
          {
            href: '/usage',
            label: 'Usage',
            note: 'what has been spent against a key, in the same token figure its daily quota is measured in',
          },
          {
            href: '/routing-policies',
            label: 'Routing policies',
            requires: 'routing:read',
            note: 'a capability with no policy is unavailable on the key form and returns no_available_model to any key that already holds it, so the policy must exist before the grant has any effect',
          },
        ]}
      />
    </div>
  );
}
