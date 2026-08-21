import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { RetentionPanel } from '@/features/retention/components/retention-panel';

export const metadata: Metadata = { title: 'Retention' };

export default function RetentionPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Retention"
        lead={
          <>
            How long each kind of record is retained before deletion.{' '}
            <strong>Deletion is permanent and cannot be undone.</strong>
          </>
        }
      >
        <p>
          A daily sweep removes anything past its window, and the control beside
          each row performs the same deletion immediately. There is no recycle
          bin: shortening a window deletes whatever then falls outside it at the
          next sweep.
        </p>
        <p>
          Set each window to the shortest period that still answers the
          questions an investigation must be able to answer. The reason to
          retain a record is the investigation of an incident; the reason not to
          is that a retained record can be disclosed.
        </p>
        <p>
          <strong>The audit log is not exempt.</strong> Deleting it removes the
          record of what was done, including the record of the deletion itself.
        </p>
      </PageHeader>
      <RetentionPanel />
      <RelatedScreens
        items={[
          {
            href: '/prompt-logs',
            label: 'Transcripts',
            requires: 'prompt_log:read',
            note: 'the most sensitive records these windows govern, and normally the shortest window here',
          },
          {
            href: '/logs',
            label: 'Audit log',
            requires: 'logs:read',
            note: 'the record a deletion here is itself written to, and the one to consider most carefully before shortening',
          },
        ]}
      />
    </div>
  );
}
