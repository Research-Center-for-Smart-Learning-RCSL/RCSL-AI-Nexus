import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { MaintenanceConsole } from '@/features/maintenance/components/maintenance-console';

export const metadata: Metadata = { title: 'Maintenance' };

export default function MaintenancePage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Maintenance"
        lead="Close the whole platform to everyone but platform administrators, and reopen it."
      />
      <MaintenanceConsole />
    </div>
  );
}
