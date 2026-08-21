import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { LogsTable } from '@/features/logs/components/logs-table';

export const metadata: Metadata = { title: 'Audit log' };

export default function LogsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Audit log"
        lead="Every administrative action, the account that took it, and whether it was permitted, including the attempts that were refused."
      >
        <p>
          The log is append-only and is never edited from this application,
          which is the property that makes it evidence rather than a view.
        </p>
        <p>
          It records <strong>what was done to the platform</strong>: keys
          issued, policies edited, models loaded, sign-ins. It does not record
          what any account asked a model, which is a separate and more sensitive
          record, disabled by default.
        </p>
      </PageHeader>
      <LogsTable />
    </div>
  );
}
