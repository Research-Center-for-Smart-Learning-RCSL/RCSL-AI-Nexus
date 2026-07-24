'use client';

import { BoxIcon, CpuIcon, KeyIcon, UsersIcon } from 'lucide-react';

import { StatCard } from '@/components/composed/stat-card';
import { MetricChart } from '@/components/composed/metric-chart';
import { ErrorState } from '@/components/composed/error-state';
import { useDashboardSummary } from '@/features/dashboard/hooks/use-dashboard';

export function DashboardOverview() {
  const { data, isLoading, error, refetch } = useDashboardSummary();

  if (error) {
    return <ErrorState error={error} onRetry={() => void refetch()} />;
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Models loaded"
          value={
            data ? `${data.models_loaded} / ${data.models_total}` : '-'
          }
          hint="Loaded against registered"
          icon={<BoxIcon className="size-4" />}
          isLoading={isLoading}
        />
        <StatCard
          label="Nodes online"
          value={data ? `${data.nodes_online} / ${data.nodes_total}` : '-'}
          hint="Node management is Phase 2"
          icon={<CpuIcon className="size-4" />}
          isLoading={isLoading}
        />
        <StatCard
          label="Active API keys"
          value={data?.api_keys_active ?? '-'}
          hint="Excludes revoked and expired"
          icon={<KeyIcon className="size-4" />}
          isLoading={isLoading}
        />
        <StatCard
          label="Users"
          value={data?.users_total ?? '-'}
          hint="Invitation only"
          icon={<UsersIcon className="size-4" />}
          isLoading={isLoading}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <MetricChart title="Requests, last 24 hours" />
        <MetricChart title="Tokens, last 24 hours" />
      </div>

      <p className="text-xs text-muted-foreground">
        Real metrics arrive in Phase 2 from Prometheus through the metrics port.
        Until then these counts come straight from the registry.
      </p>
    </div>
  );
}
