import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { UsageAnalyticsView } from '@/features/usage/components/usage-analytics';

export const metadata: Metadata = { title: 'Usage' };

export default function UsagePage() {
  return (
    <div className="space-y-4">
      {/* Scope-neutral, because who this screen counts depends on the reader:
          `usage:read_all` sees the tenant, everyone else sees themselves. The
          view below says which, since it is the part with a session to ask. */}
      <PageHeader
        title="Usage analytics"
        lead="What has been consumed, counted from a record written for every served request."
      >
        <p>
          Tokens here are the figure a key&apos;s daily quota is measured
          against, so this is the screen that establishes whether a quota
          requires raising or an unexpected cost is genuine.
        </p>
        <p>
          Both the input submitted and the output produced are counted.
          Automated callers resend the entire conversation on every turn, so a
          long task costs considerably more than its replies alone suggest;
          this is usually the explanation where a figure appears too high for
          the work done. A record is written when a request finishes, including
          one stopped part way, so cancelled work also appears.
        </p>
      </PageHeader>
      <UsageAnalyticsView />
    </div>
  );
}
