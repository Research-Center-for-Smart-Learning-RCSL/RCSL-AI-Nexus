import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { RetentionPanel } from '@/features/retention/components/retention-panel';

export const metadata: Metadata = { title: 'Retention' };

export default function RetentionPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Retention</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          How long each kind of record is kept before it is deleted. A daily
          sweep removes anything past its window, and the button beside each row
          does the same immediately. <strong>Both are permanent.</strong> There
          is no recycle bin and no undo; shortening a window deletes what now
          falls outside it on the next sweep.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Set each window to the shortest period that still answers the
          questions an investigation has to be able to answer — the reason to keep a record
          is investigating an incident, and the reason not to is that a record
          kept is a record that can leak. <strong>The audit log is not
          exempt</strong>: deleting it removes the record of what was done,
          including the record of the deletion.
        </p>
      </div>
      <RetentionPanel />
      <RelatedScreens
        items={[
          {
            href: '/prompt-logs',
            label: 'Transcripts',
            requires: 'prompt_log:read',
            note: 'the most sensitive records these windows govern, and the shortest window here should normally be theirs',
          },
          {
            href: '/logs',
            label: 'Audit log',
            requires: 'logs:read',
            note: 'the record a deletion here is itself written to, and the one to think hardest about before shortening',
          },
        ]}
      />
    </div>
  );
}
