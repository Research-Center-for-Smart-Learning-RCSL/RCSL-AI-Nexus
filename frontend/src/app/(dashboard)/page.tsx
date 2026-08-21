import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { DashboardOverview } from '@/features/dashboard/components/dashboard-overview';

export const metadata: Metadata = { title: 'Dashboard' };

export default function DashboardPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Dashboard"
        lead="The state of the installation in one view: what is being requested of it, what is serving those requests, and what requires attention."
      >
        <p>
          Every figure on this screen summarises a screen listed below. Nothing
          is edited here; follow a figure to the screen that owns it.
        </p>
      </PageHeader>
      <DashboardOverview />
      <RelatedScreens
        items={[
          {
            href: '/usage',
            label: 'Usage',
            note: 'the same consumption figures over a selected period, and per key rather than in total',
          },
          {
            href: '/models',
            label: 'Models',
            requires: 'model:read',
            note: 'which models are loaded and which are only registered, which determines whether a request can be served',
          },
          {
            href: '/nodes',
            label: 'Nodes',
            requires: 'node:read',
            note: 'the capacity remaining on the machine behind the installation',
          },
        ]}
      />
    </div>
  );
}
