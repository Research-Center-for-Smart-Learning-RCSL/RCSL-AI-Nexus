import type { Metadata } from 'next';

import { ApiKeyTable } from '@/features/api-keys/components/api-key-table';

export const metadata: Metadata = { title: 'API keys' };

export default function ApiKeysPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">API keys</h1>
        <p className="text-sm text-muted-foreground">
          Keys authenticate applications against the public gateway. Only a
          peppered hash is stored, so a key is shown once and never again.
        </p>
      </div>
      <ApiKeyTable />
    </div>
  );
}
