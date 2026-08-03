import type { Metadata } from 'next';

import { UsageAnalyticsView } from '@/features/usage/components/usage-analytics';

export const metadata: Metadata = { title: 'Usage' };

export default function UsagePage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Usage analytics</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          What was actually spent, counted from usage records per tenant. These
          are produced tokens only, which is the same number a key&apos;s daily
          quota is measured against.
        </p>
      </div>
      <UsageAnalyticsView />
    </div>
  );
}
