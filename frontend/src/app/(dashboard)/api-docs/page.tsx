import type { Metadata } from 'next';

import { ApiReference } from '@/features/gateway/components/api-reference';

export const metadata: Metadata = { title: 'API' };

export default function ApiDocsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-heading text-lg font-semibold">API</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          How to call the inference gateway with a key issued here. The schema
          endpoints are disabled on the gateway itself, so this page is the
          contract.
        </p>
      </div>
      <ApiReference />
    </div>
  );
}
