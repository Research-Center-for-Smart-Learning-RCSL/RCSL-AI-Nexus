import type { ReactNode } from 'react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export type StatCardProps = {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  /** Signed change, rendered next to the value. Phase 2 supplies real deltas. */
  delta?: { value: string; direction: 'up' | 'down' | 'flat' };
  isLoading?: boolean;
  className?: string;
};

const DELTA_TONE = {
  up: 'text-emerald-600 dark:text-emerald-400',
  down: 'text-destructive',
  flat: 'text-muted-foreground',
} as const;

export function StatCard({
  label,
  value,
  hint,
  icon,
  delta,
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
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-semibold tabular-nums">{value}</span>
            {delta ? (
              <span className={cn('text-xs', DELTA_TONE[delta.direction])}>
                {delta.value}
              </span>
            ) : null}
          </div>
        )}
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}
