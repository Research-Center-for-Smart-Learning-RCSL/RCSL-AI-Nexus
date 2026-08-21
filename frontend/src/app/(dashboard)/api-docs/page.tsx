import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { ApiReference } from '@/features/gateway/components/api-reference';

export const metadata: Metadata = { title: 'API reference' };

export default function ApiDocsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="API reference"
        lead="The contract for calling this deployment from external code using a key issued here: the address to send to, the structure of a request, every field a request accepts, and the meaning of each error code."
      >
        <p>
          Requests name a <strong>capability</strong> rather than a model. This
          is the principal respect in which the platform differs from
          general-purpose providers.
        </p>
        <p>
          The gateway serves no machine-readable schema, so this page
          constitutes the contract rather than a summary of one. Its contents
          are rendered from the running deployment, so the address and the list
          of capabilities are those a key will encounter.
        </p>
      </PageHeader>
      <ApiReference />
    </div>
  );
}
