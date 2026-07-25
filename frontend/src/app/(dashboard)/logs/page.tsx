import type { Metadata } from 'next';

import { LogsTable } from '@/features/logs/components/logs-table';

export const metadata: Metadata = { title: 'Logs' };

export default function LogsPage() {
  return (
    <div className="space-y-4">
      <h1 className="font-heading text-lg font-semibold">Audit log</h1>
      <LogsTable />
    </div>
  );
}
