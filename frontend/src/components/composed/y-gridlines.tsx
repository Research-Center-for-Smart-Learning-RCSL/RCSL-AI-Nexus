import { scaleY, yTicks, type Plot } from '@/components/composed/chart-geometry';

export type YGridlinesProps = {
  plot: Plot;
  formatValue?: (value: number) => string;
};

const defaultFormat = (value: number) => value.toLocaleString();

export function YGridlines({ plot, formatValue = defaultFormat }: YGridlinesProps) {
  return (
    <>
      {yTicks(plot.axisMax).map((v) => {
        const y = scaleY(v, plot);
        const isEndpoint = v === 0 || v === plot.axisMax;
        return (
          <g key={v}>
            <line
              x1={plot.x0}
              x2={plot.x1}
              y1={y}
              y2={y}
              className={isEndpoint ? 'stroke-border' : 'stroke-border/50'}
              strokeWidth={1}
              strokeDasharray={isEndpoint ? undefined : '2 4'}
            />
            <text
              x={plot.x0 - 6}
              y={y}
              textAnchor="end"
              dominantBaseline="middle"
              className="fill-muted-foreground text-[10px]"
            >
              {formatValue(v)}
            </text>
          </g>
        );
      })}
    </>
  );
}
