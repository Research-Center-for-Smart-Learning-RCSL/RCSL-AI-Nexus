import type { Metadata } from 'next';

import { RetentionPanel } from '@/features/retention/components/retention-panel';

export const metadata: Metadata = { title: 'Retention' };

export default function RetentionPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Retention</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          How long each kind of record is kept. A daily sweep deletes anything
          past its window; the button beside each one does the same immediately.
          Both are permanent, and the audit log is not exempt — deleting it
          removes the record of what was done, including the deletion.
        </p>
      </div>
      <RetentionPanel />
    </div>
  );
}
