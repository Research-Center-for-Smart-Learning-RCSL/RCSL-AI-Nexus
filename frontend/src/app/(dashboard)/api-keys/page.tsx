import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { ApiKeyTable } from '@/features/api-keys/components/api-key-table';

export const metadata: Metadata = { title: 'API keys' };

export default function ApiKeysPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">API keys</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          A key lets code and tools outside this deployment call it.
          A key is <strong>shown once, when it is created</strong> — only a
          one-way hash is stored, so a lost key is replaced rather than
          recovered. Each key is scoped to the capabilities it may ask for;
          issue the narrowest set that does the job, since a key that can reach
          everything is worth more to whoever finds it.
        </p>
      </div>
      <ApiKeyTable />
      <RelatedScreens
        items={[
          {
            href: '/api-docs',
            label: 'API reference',
            note: 'where to send a key and what a request looks like, rendered from this deployment',
          },
          {
            href: '/agent-setup',
            label: 'Connect an agent',
            note: 'the same key configured in a coding agent, step by step, including the two limits whose defaults are wrong for that use',
          },
          {
            href: '/usage',
            label: 'Usage',
            note: 'what has actually been spent against a key, in the same token figure its daily quota is measured in',
          },
          {
            href: '/routing-policies',
            label: 'Routing policies',
            requires: 'routing:read',
            note: 'a capability with no policy is greyed out on the key form and answers no_available_model for any key that already holds one, so a policy has to exist there before granting it here is worth anything',
          },
        ]}
      />
    </div>
  );
}
