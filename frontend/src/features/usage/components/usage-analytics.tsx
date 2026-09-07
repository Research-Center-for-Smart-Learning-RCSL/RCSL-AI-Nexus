'use client';

import { useState } from 'react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/composed/error-state';
import { MetricChart, type MetricSeries } from '@/components/composed/metric-chart';
import { useSession } from '@/lib/session';
import { UsageRecordsTable } from '@/features/usage/components/usage-records-table';
import { useUsage } from '@/features/usage/hooks/use-usage';
import {
  USAGE_RANGES,
  type CompactionSummary,
  type UsageAnalytics,
  type UsagePoint,
  type UsageRange,
} from '@/features/usage/schema';

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

const TIER_LABEL: Record<number, string> = {
  0: 'Tier 0, tool definitions',
  1: 'Tier 1, old tool results',
  2: 'Tier 2, oldest turns summarised',
};

/**
 * Compaction over the same window as the charts above.
 *
 * A ratio rather than a count, because the count alone answers nothing: eleven
 * compactions is unremarkable against forty thousand requests and alarming
 * against twelve. The denominator comes from the totals already on the
 * response.
 *
 * Rendered even at zero. An operator who has just switched the setting on for a
 * key is asking whether it is doing anything, and a card that disappears when
 * the answer is "no" leaves them unable to tell that from a screen that never
 * had the card.
 */
function CompactionSummaryCard({
  summary,
  totals,
}: {
  summary: CompactionSummary;
  totals: UsagePoint[];
}) {
  const requests = totals.reduce((n, p) => n + p.requests, 0);
  const share = requests > 0 ? (summary.requests / requests) * 100 : 0;
  return (
    <section className="rounded-lg border p-4" aria-labelledby="compaction-heading">
      <h3 id="compaction-heading" className="text-sm font-medium">
        Context compaction
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Requests whose prompt was reduced before it reached the model, rather than refused for
        exceeding the context limit. Controlled per API key.
      </p>
      <dl className="mt-3 grid gap-3 sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted-foreground">Compacted</dt>
          <dd className="text-lg font-semibold tabular-nums">
            {summary.requests.toLocaleString()}
            {requests > 0 ? (
              <span className="ml-1 text-sm font-normal text-muted-foreground">
                of {requests.toLocaleString()} ({share.toFixed(1)}%)
              </span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Prompt tokens removed</dt>
          <dd className="text-lg font-semibold tabular-nums">
            {summary.tokens_removed.toLocaleString()}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">By tier</dt>
          <dd className="text-sm">
            {summary.by_tier.length === 0 ? (
              <span className="text-muted-foreground">None in this range</span>
            ) : (
              <ul>
                {summary.by_tier.map((t) => (
                  <li key={t.tier} className="tabular-nums">
                    {TIER_LABEL[t.tier] ?? `Tier ${t.tier}`}: {t.requests.toLocaleString()}
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
}

export function UsageAnalyticsView() {
  const [range, setRange] = useState<UsageRange>('24h');
  // Which usage this screen is for is a property of the reader, so it is
  // resolved here rather than passed in: the page above is a server component
  // and has no session to ask. Everybody holds `usage:read_own`, so there is no
  // third branch where the screen has nothing to show.
  const { can } = useSession();
  const mine = !can('usage:read_all');
  const { data, isLoading, error, refetch } = useUsage(range, { mine });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {mine
            ? 'Your own usage: everything your API keys produced, plus your admin chat. Other accounts are not counted.'
            : 'From usage records, per tenant. Live operational metrics are in Grafana.'}
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
          {data ? <CompactionSummaryCard summary={data.compaction} totals={data.totals} /> : null}
          {/* The rows behind every count above. Below the charts rather than on
              a screen of its own: the question it answers — "which request was
              that?" — is the one somebody asks while looking at a figure they
              did not expect. */}
          <UsageRecordsTable />
        </>
      )}
    </div>
  );
}
