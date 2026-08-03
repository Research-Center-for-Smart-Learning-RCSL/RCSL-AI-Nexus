'use client';

import { BoxIcon, CpuIcon, KeyIcon, UsersIcon } from 'lucide-react';

import { StatCard } from '@/components/composed/stat-card';
import { MetricChart, type MetricSeries } from '@/components/composed/metric-chart';
import { ErrorState } from '@/components/composed/error-state';
import { useDashboardSummary } from '@/features/dashboard/hooks/use-dashboard';
import { useUsage } from '@/features/usage/hooks/use-usage';

export function DashboardOverview() {
  const { data, isLoading, error, refetch } = useDashboardSummary();
  // The charts read the usage-analytics endpoint directly; the stat tiles keep
  // their own 24h totals from /dashboard.
  const usage = useUsage('24h');
  const requests: MetricSeries[] | undefined = usage.data
    ? [{ label: 'Requests', points: usage.data.totals.map((p) => ({ t: p.t, v: p.requests })) }]
    : undefined;
  const tokens: MetricSeries[] | undefined = usage.data
    ? [{ label: 'Tokens', points: usage.data.totals.map((p) => ({ t: p.t, v: p.tokens })) }]
    : undefined;

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
          hint="From the node heartbeat"
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

      {/* The charts read a second endpoint, and its failure used to be silent:
          with no data and nothing loading, MetricChart says "No activity in
          this range", which is a claim about the deployment rather than about
          the request. An operator checking whether traffic had stopped would
          have been told that it had. */}
      {usage.error ? (
        <ErrorState
          title="Could not load the usage charts"
          error={usage.error}
          onRetry={() => void usage.refetch()}
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <MetricChart
            title="Requests, last 24 hours"
            series={requests}
            isLoading={usage.isLoading}
          />
          <MetricChart title="Tokens, last 24 hours" series={tokens} isLoading={usage.isLoading} />
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Request and token counts come from usage records. Live operational
        metrics (memory, latency, node health) are in Grafana.
      </p>
    </div>
  );
}
