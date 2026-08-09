import type { Metadata } from 'next';

import { LogsTable } from '@/features/logs/components/logs-table';

export const metadata: Metadata = { title: 'Logs' };

export default function LogsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Audit log</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Every administrative action, with who took it and whether it was
          allowed — including the attempts that were refused, which are the ones
          worth reading. Append-only and never edited from here, which is what
          makes it evidence rather than a view.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          This records <strong>what was done to the platform</strong>: keys
          issued, policies edited, models loaded, sign-ins. It does not record
          what anyone asked a model, which is a separate and more sensitive
          thing, kept off by default.
        </p>
      </div>
      <LogsTable />
    </div>
  );
}
