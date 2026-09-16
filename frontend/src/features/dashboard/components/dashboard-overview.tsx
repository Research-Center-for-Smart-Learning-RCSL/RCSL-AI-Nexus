'use client';

import { useMemo } from 'react';

import { ActivityIcon, BoxIcon, CpuIcon, HashIcon, KeyIcon, UsersIcon } from 'lucide-react';

import { Sparkline } from '@/components/composed/sparkline';
import { StatCard } from '@/components/composed/stat-card';
import { MetricChart, type MetricSeries } from '@/components/composed/metric-chart';
import { ErrorState } from '@/components/composed/error-state';
import type { ChartPoint } from '@/components/composed/chart-geometry';
import { useDashboardSummary } from '@/features/dashboard/hooks/use-dashboard';
import type { DashboardTrendPoint } from '@/features/dashboard/schema';
import { useUsage } from '@/features/usage/hooks/use-usage';

function trendPoints(trends: DashboardTrendPoint[], key: keyof Omit<DashboardTrendPoint, 't'>): ChartPoint[] {
  return trends.map((p) => ({ t: p.t, v: p[key] }));
}

export function DashboardOverview() {
  const { data, isLoading, error, refetch } = useDashboardSummary();
  const usage = useUsage('24h');
  const requests: MetricSeries[] | undefined = usage.data
    ? [{ label: 'Requests', points: usage.data.totals.map((p) => ({ t: p.t, v: p.requests })) }]
    : undefined;
  const tokens: MetricSeries[] | undefined = usage.data
    ? [{ label: 'Tokens', points: usage.data.totals.map((p) => ({ t: p.t, v: p.tokens })) }]
    : undefined;
  const trends = useMemo(() => data?.trends ?? [], [data]);

  if (error) {
    return <ErrorState error={error} onRetry={() => void refetch()} />;
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard
          label="Models loaded"
          value={
            data ? `${data.models_loaded} / ${data.models_total}` : '—'
          }
          sparkline={trends.length > 0 ? <Sparkline points={trendPoints(trends, 'models_loaded')} label="Models loaded trend" className="text-chart-1" /> : undefined}
          hint="Registered as loaded — Models shows where the runtime disagrees, and routing follows the runtime"
          icon={<BoxIcon className="size-4" />}
          isLoading={isLoading}
        />
        <StatCard
          label="Nodes online"
          value={data ? `${data.nodes_online} / ${data.nodes_total}` : '—'}
          sparkline={trends.length > 0 ? <Sparkline points={trendPoints(trends, 'nodes_online')} label="Nodes online trend" className="text-chart-1" /> : undefined}
          hint="From the node heartbeat"
          icon={<CpuIcon className="size-4" />}
          isLoading={isLoading}
        />
        <StatCard
          label="Active API keys"
          value={data?.api_keys_active ?? '—'}
          sparkline={trends.length > 0 ? <Sparkline points={trendPoints(trends, 'api_keys_active')} label="API keys trend" className="text-chart-1" /> : undefined}
          hint="Excludes revoked and expired"
          icon={<KeyIcon className="size-4" />}
          isLoading={isLoading}
        />
        <StatCard
          label="Users"
          value={data?.users_total ?? '—'}
          sparkline={trends.length > 0 ? <Sparkline points={trendPoints(trends, 'users_total')} label="Users trend" className="text-chart-1" /> : undefined}
          hint="Invitation only"
          icon={<UsersIcon className="size-4" />}
          isLoading={isLoading}
        />
        <StatCard
          label="Requests (24h)"
          value={data?.requests_last_24h?.toLocaleString() ?? '—'}
          sparkline={requests && <Sparkline points={requests[0].points} label="Request trend, last 24 hours" className="text-chart-1" />}
          icon={<ActivityIcon className="size-4" />}
          isLoading={isLoading || usage.isLoading}
        />
        <StatCard
          label="Tokens (24h)"
          value={data?.tokens_last_24h?.toLocaleString() ?? '—'}
          sparkline={tokens && <Sparkline points={tokens[0].points} label="Token trend, last 24 hours" className="text-chart-2" />}
          icon={<HashIcon className="size-4" />}
          isLoading={isLoading || usage.isLoading}
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
