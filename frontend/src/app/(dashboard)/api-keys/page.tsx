import type { Metadata } from 'next';
import Link from 'next/link';

import { ApiKeyTable } from '@/features/api-keys/components/api-key-table';

export const metadata: Metadata = { title: 'API keys' };

export default function ApiKeysPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">API keys</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Keys authenticate applications against the public gateway. Only a
          peppered hash is stored, so a key is shown once and never again. The{' '}
          <Link href="/api-docs" className="underline">
            API reference
          </Link>{' '}
          covers where to send one and what the endpoint expects.
        </p>
      </div>
      <ApiKeyTable />
    </div>
  );
}
