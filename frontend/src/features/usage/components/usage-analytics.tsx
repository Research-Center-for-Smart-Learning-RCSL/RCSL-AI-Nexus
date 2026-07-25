'use client';

import { useState } from 'react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/composed/error-state';
import { MetricChart, type MetricSeries } from '@/components/composed/metric-chart';
import { useUsage } from '@/features/usage/hooks/use-usage';
import { USAGE_RANGES, type UsageAnalytics, type UsageRange } from '@/features/usage/schema';

const RANGE_LABEL: Record<UsageRange, string> = {
  '24h': 'Last 24 hours',
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
};

function totalsSeries(data: UsageAnalytics, key: 'requests' | 'tokens'): MetricSeries[] {
  return [{ label: key === 'requests' ? 'Requests' : 'Tokens', points: data.totals.map((p) => ({ t: p.t, v: p[key] })) }];
}

function byCapabilitySeries(data: UsageAnalytics): MetricSeries[] {
  return data.by_capability.map((s) => ({
    label: s.capability,
    points: s.points.map((p) => ({ t: p.t, v: p.requests })),
  }));
}

export function UsageAnalyticsView() {
  const [range, setRange] = useState<UsageRange>('24h');
  const { data, isLoading, error, refetch } = useUsage(range);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          From usage records, per tenant. Live operational metrics are in Grafana.
        </p>
        <div className="flex gap-1">
          {USAGE_RANGES.map((r) => (
            <Button
              key={r}
              size="sm"
              variant={r === range ? 'default' : 'outline'}
              onClick={() => setRange(r)}
              aria-pressed={r === range}
            >
              {r}
            </Button>
          ))}
        </div>
      </div>

      {error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <div className={cn('grid gap-4 lg:grid-cols-2')}>
            <MetricChart
              title={`Requests, ${RANGE_LABEL[range].toLowerCase()}`}
              series={data ? totalsSeries(data, 'requests') : undefined}
              isLoading={isLoading}
            />
            <MetricChart
              title={`Tokens, ${RANGE_LABEL[range].toLowerCase()}`}
              series={data ? totalsSeries(data, 'tokens') : undefined}
              isLoading={isLoading}
            />
          </div>
          <MetricChart
            title="Requests by capability"
            series={data ? byCapabilitySeries(data) : undefined}
            isLoading={isLoading}
          />
        </>
      )}
    </div>
  );
}
