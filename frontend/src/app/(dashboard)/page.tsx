import type { Metadata } from 'next';

import { DashboardOverview } from '@/features/dashboard/components/dashboard-overview';

export const metadata: Metadata = { title: 'Dashboard' };

export default function DashboardPage() {
  return (
    <div className="space-y-4">
      <h1 className="font-heading text-lg font-semibold">Dashboard</h1>
      <DashboardOverview />
    </div>
  );
}
