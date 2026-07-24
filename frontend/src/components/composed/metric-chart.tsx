'use client';

/**
 * Placeholder. Charts belong to Dashboard and Usage Analytics, both Phase 2,
 * and frontend.md section 7 requires the chart library choice to be verified at
 * implementation time rather than assumed: Tremor's distribution model has
 * shifted toward copy-in source, with the supply-chain caveat in security.md
 * section 10. Recharts is the fallback.
 *
 * Deliberately renders a labelled placeholder rather than pulling in a library
 * now, so that nothing has to be un-chosen later.
 */

import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export type MetricSeries = {
  label: string;
  points: { t: string; v: number }[];
};

export type MetricChartProps = {
  title: string;
  series?: MetricSeries[];
  className?: string;
};

export function MetricChart({ title, series, className }: MetricChartProps) {
  const pointCount = series?.reduce((sum, s) => sum + s.points.length, 0) ?? 0;

  return (
    <Card className={cn('h-full', className)}>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex h-40 items-center justify-center rounded-lg border border-dashed text-center text-xs text-muted-foreground">
          <span>
            Charts are Phase 2. Library choice pending (frontend.md section 7).
            <br />
            {pointCount} point{pointCount === 1 ? '' : 's'} available.
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
