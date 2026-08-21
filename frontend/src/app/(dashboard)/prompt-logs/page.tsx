import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { PromptLogsTable } from '@/features/prompt-logs/components/prompt-logs-table';

export const metadata: Metadata = { title: 'Transcripts' };

export default function PromptLogsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Transcripts"
        lead="What was submitted to a model and what it returned, captured only while a debug window is open on an API key or a user account."
      >
        <p>
          The platform records metadata by default and nothing further, so an
          empty list here is the normal state rather than a fault.
        </p>
        <p>
          These records contain unpublished research material. They are retained
          for days rather than months — the window is set on the Retention
          screen — and opening one is itself recorded.
        </p>
      </PageHeader>
      <PromptLogsTable />
      <RelatedScreens
        items={[
          {
            href: '/api-keys',
            label: 'API keys',
            note: 'where capture is enabled: opening a debug window on a key is what causes records to appear here, and the window closes itself',
          },
          {
            href: '/retention',
            label: 'Retention',
            requires: 'retention:write',
            note: 'how long these are retained once captured, which should be the shortest window on that screen',
          },
          {
            href: '/logs',
            label: 'Audit log',
            requires: 'logs:read',
            note: 'where the fact that one of these was opened is recorded',
          },
        ]}
      />
    </div>
  );
}
