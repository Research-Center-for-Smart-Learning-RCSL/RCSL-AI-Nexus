import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { DashboardOverview } from '@/features/dashboard/components/dashboard-overview';

export const metadata: Metadata = { title: 'Dashboard' };

export default function DashboardPage() {
  return (
    <div className="space-y-4">
      {/* Had no description at all until 2026-08-09, on the one screen a
          reader is most likely to arrive at first. */}
      <div>
        <h1 className="font-heading text-lg font-semibold">Dashboard</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          The state of the installation in one view: what is being asked of it,
          what is answering, and whether anything needs attention. It summarises
          the screens below rather than holding anything of its own, so nothing
          here is edited — follow a figure to the screen that owns it.
        </p>
      </div>
      <DashboardOverview />
      <RelatedScreens
        items={[
          {
            href: '/usage',
            label: 'Usage',
            note: 'the same consumption figures over a period you choose, and per key rather than in total',
          },
          {
            href: '/models',
            label: 'Models',
            requires: 'model:read',
            note: 'what is loaded and what is merely registered, which is what decides whether a request can be served at all',
          },
          {
            href: '/nodes',
            label: 'Nodes',
            requires: 'node:read',
            note: 'the capacity left on the machine behind all of it',
          },
        ]}
      />
    </div>
  );
}
