import type { ReactNode } from 'react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export type StatCardProps = {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  isLoading?: boolean;
  className?: string;
};

/**
 * A single figure, its label, and what the figure is counted from.
 *
 * There is no trend indicator. One was carried here unused for long enough to
 * acquire a comment promising real deltas in a later phase; a control nothing
 * renders is not a feature in reserve, it is a claim in the type signature that
 * the screens do not make.
 */
export function StatCard({
  label,
  value,
  hint,
  icon,
  isLoading,
  className,
}: StatCardProps) {
  return (
    <Card data-slot="stat-card" className={cn('gap-2', className)}>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-0">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
        {icon ? <span className="text-muted-foreground">{icon}</span> : null}
      </CardHeader>
      <CardContent className="space-y-1">
        {isLoading ? (
          <div className="h-7 w-24 animate-pulse rounded bg-muted" />
        ) : (
          <span className="text-2xl font-semibold tabular-nums">{value}</span>
        )}
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}
