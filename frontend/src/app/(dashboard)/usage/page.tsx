import type { Metadata } from 'next';

import { UsageAnalyticsView } from '@/features/usage/components/usage-analytics';

export const metadata: Metadata = { title: 'Usage' };

export default function UsagePage() {
  return (
    <div className="space-y-4">
      <h1 className="font-heading text-lg font-semibold">Usage analytics</h1>
      <UsageAnalyticsView />
    </div>
  );
}
