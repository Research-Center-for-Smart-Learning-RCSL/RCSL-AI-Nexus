'use client';

import { cn } from '@/lib/utils';
import {
  sparklineArea,
  sparklinePath,
  type ChartPoint,
  type SparkPlot,
} from '@/components/composed/chart-geometry';

export type SparklineProps = {
  points: ChartPoint[];
  width?: number;
  height?: number;
  className?: string;
  label?: string;
};

export function Sparkline({
  points,
  width = 80,
  height = 24,
  className,
  label,
}: SparklineProps) {
  const valid = points.filter((p) => !Number.isNaN(Date.parse(p.t)));
  if (valid.length < 2) return null;

  const values = valid.map((p) => p.v);
  const spark: SparkPlot = {
    width,
    height,
    minV: Math.min(...values),
    maxV: Math.max(...values),
  };

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn('h-full w-full', className)}
      role="img"
      aria-label={label}
    >
      <path d={sparklineArea(valid, spark)} fill="currentColor" opacity={0.15} />
      <path
        d={sparklinePath(valid, spark)}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
