import type { Metadata } from 'next';

import { ApiReference } from '@/features/gateway/components/api-reference';

export const metadata: Metadata = { title: 'API' };

export default function ApiDocsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-heading text-lg font-semibold">API reference</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          How to call this deployment from your own code with a key issued here:
          the address to send to, the shape of a request, every field a request
          accepts, and what each error code means. Requests name a{' '}
          <strong>capability</strong> rather than a model, which is the one
          place this platform differs from providers you may have used before.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          The gateway serves no machine-readable schema of its own, so this page
          is the contract rather than a summary of one. Everything on it is
          rendered from the running deployment, so the address and the list of
          capabilities are the ones your key will actually meet.
        </p>
      </div>
      <ApiReference />
    </div>
  );
}
