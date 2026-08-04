import type { Metadata } from 'next';

import { UsageAnalyticsView } from '@/features/usage/components/usage-analytics';

export const metadata: Metadata = { title: 'Usage' };

export default function UsagePage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Usage analytics</h1>
        {/* Scope-neutral, because who this screen counts depends on the reader:
            `usage:read_all` sees the tenant, everyone else sees themselves. The
            view below says which, since it is the part with a session to ask. */}
        <p className="max-w-prose text-sm text-muted-foreground">
          What was actually spent, counted from usage records. Tokens here are
          the same figure a key&apos;s daily quota is measured against.
        </p>
      </div>
      <UsageAnalyticsView />
    </div>
  );
}
