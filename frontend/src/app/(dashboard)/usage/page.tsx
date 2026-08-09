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
          What has actually been spent, counted from a record written for every
          served request. Tokens here are the same figure a key&apos;s daily
          quota is measured against, so this is the screen that answers whether
          a quota needs raising or an unexpected cost is real.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Both the words sent and the words produced are counted. Automated
          callers resend the whole conversation on every turn, so a long task
          costs far more than its replies suggest — usually the explanation when
          a figure looks too high for the work done. Records are written when a
          request finishes, including one that was stopped part way, so
          cancelled work still appears.
        </p>
      </div>
      <UsageAnalyticsView />
    </div>
  );
}
