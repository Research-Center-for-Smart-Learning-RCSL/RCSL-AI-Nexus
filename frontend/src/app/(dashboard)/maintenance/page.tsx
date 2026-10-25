import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { MaintenanceConsole } from '@/features/maintenance/components/maintenance-console';
import { UnknownOperations } from '@/features/maintenance/components/unknown-operations';

export const metadata: Metadata = { title: 'Maintenance' };

export default function MaintenancePage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Maintenance"
        lead="Close the whole platform to everyone but platform administrators, release and restore its runtimes, and clear a node blocked by an operation of unknown outcome."
      />
      <MaintenanceConsole />
      <UnknownOperations />
    </div>
  );
}
