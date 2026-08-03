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
          allowed. Append-only and never edited from here, which is what makes
          it evidence rather than a view.
        </p>
      </div>
      <LogsTable />
    </div>
  );
}
