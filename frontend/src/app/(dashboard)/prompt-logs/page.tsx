import type { Metadata } from 'next';

import { PromptLogsTable } from '@/features/prompt-logs/components/prompt-logs-table';

export const metadata: Metadata = { title: 'Transcripts' };

export default function PromptLogsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Transcripts</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          What was actually typed and what the model wrote back, captured only
          while a debug window is open on an API key or a user account. The
          platform records metadata by default and nothing else, so an empty
          list here is the normal state rather than a fault.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          These are researchers’ unpublished ideas. They are kept for days
          rather than months — the window on the Retention screen — and opening
          one records that you read it.
        </p>
      </div>
      <PromptLogsTable />
    </div>
  );
}
