import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { RefusalsTable } from '@/features/refusals/components/refusals-table';

export const metadata: Metadata = { title: 'Refusals' };

export default function RefusalsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Refusals"
        lead="Every request this platform declined, with the message returned to the caller and the figures that accompanied it."
      >
        <p>
          Each reader sees their own refusals by default, and every
          reader&apos;s with{' '}
          <code className="font-mono">refusal:read_all</code>. A refusal is
          identified by the request id the caller was given, so a report of a
          failure can be resolved to the record of it.
        </p>
        <p>
          Nothing recorded here exceeds what the caller was already told. No
          request content is stored and no model is named. The operator-facing
          detail that accompanies an error is never written to the row: it
          reaches a response only while an administrator holds a debug window
          open on that credential, and does not reach this table even then.
        </p>
      </PageHeader>
      <RefusalsTable />
      <RelatedScreens
        items={[
          {
            href: '/logs',
            label: 'Audit log',
            requires: 'logs:read',
            note: 'what accounts did, rather than what they were refused; a failed sign-in or an authorization denial is recorded there and not here',
          },
          {
            href: '/usage',
            label: 'Usage',
            requires: 'usage:read_own',
            note: 'the requests that succeeded, against the quota a 429 here would have counted towards',
          },
          {
            href: '/retention',
            label: 'Retention',
            requires: 'retention:write',
            note: 'how long these are retained — a ceiling as well as a floor, since a year of refusals describes how an account is used',
          },
        ]}
      />
    </div>
  );
}
