'use client';

import { useRef, useState } from 'react';

import { cn } from '@/lib/utils';
import {
  categoricalBarRects,
  plotArea,
  scaleY,
  yTicks,
} from '@/components/composed/chart-geometry';
import {
  formatScore,
  shortModelLabel,
  type EvaluationReport,
} from '@/features/evaluations/schema';

const VIEW_W = 640;
const VIEW_H = 200;
const MARGIN = { top: 12, right: 16, bottom: 36, left: 44 };

export function ModelScoreChart({ report }: { report: EvaluationReport }) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const sorted = report.models
    .slice()
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

  if (sorted.length === 0) return null;

  const best = sorted[0]?.score ?? 0;
  const items = sorted.map((m) => ({ label: shortModelLabel(m.model_ref), v: (m.score ?? 0) * 100 }));

  const dummySeries = [{ label: '', points: [{ t: '0', v: 0 }, { t: '1', v: 100 }] }];
  const plot = { ...plotArea(dummySeries, VIEW_W, VIEW_H, MARGIN), axisMax: 100 };
  const bars = categoricalBarRects(items, plot, 8);
  const ticks = yTicks(100);

  function onMove(event: React.PointerEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg || bars.length === 0) return;
    const rect = svg.getBoundingClientRect();
    const vbX = ((event.clientX - rect.left) / rect.width) * VIEW_W;
    let nearest = 0;
    let bestDist = Infinity;
    for (let i = 0; i < bars.length; i++) {
      const center = bars[i].x + bars[i].width / 2;
      const dist = Math.abs(center - vbX);
      if (dist < bestDist) { bestDist = dist; nearest = i; }
    }
    setHoverIdx(nearest);
  }

  function onKeyDown(event: React.KeyboardEvent<SVGSVGElement>) {
    if (bars.length === 0) return;
    const current = hoverIdx ?? -1;
    switch (event.key) {
      case 'ArrowRight': setHoverIdx(Math.min(bars.length - 1, current + 1)); break;
      case 'ArrowLeft': setHoverIdx(Math.max(0, current < 0 ? bars.length - 1 : current - 1)); break;
      case 'Home': setHoverIdx(0); break;
      case 'End': setHoverIdx(bars.length - 1); break;
      case 'Escape': setHoverIdx(null); return;
      default: return;
    }
    event.preventDefault();
  }

  const hovered = hoverIdx !== null ? sorted[hoverIdx] : null;

  return (
    <section className="space-y-2">
      <h3 className="font-heading text-sm font-semibold">Score by model</h3>
      <div className="relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          className="h-48 w-full touch-none rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          role="img"
          aria-label={`Model scores. ${bars.length} models. Focus and use arrow keys to read values.`}
          tabIndex={0}
          onPointerMove={onMove}
          onPointerLeave={() => setHoverIdx(null)}
          onKeyDown={onKeyDown}
          onBlur={() => setHoverIdx(null)}
        >
          {ticks.map((v) => {
            const y = scaleY(v, plot);
            const isEndpoint = v === 0 || v === 100;
            return (
              <g key={v}>
                <line
                  x1={plot.x0} x2={plot.x1} y1={y} y2={y}
                  className={isEndpoint ? 'stroke-border' : 'stroke-border/50'}
                  strokeWidth={1}
                  strokeDasharray={isEndpoint ? undefined : '2 4'}
                />
                <text
                  x={plot.x0 - 6} y={y}
                  textAnchor="end" dominantBaseline="middle"
                  className="fill-muted-foreground text-[10px]"
                >
                  {v}%
                </text>
              </g>
            );
          })}

          {bars.map((bar, i) => {
            const isBest = best > 0 && Math.abs((sorted[i].score ?? 0) - best) < 0.001;
            return (
              <g key={sorted[i].model_ref}>
                <rect
                  x={bar.x} y={bar.y} width={bar.width} height={Math.max(0, bar.height)}
                  rx={2}
                  className={cn(
                    'transition-opacity',
                    isBest ? 'fill-primary' : 'fill-primary/40',
                    hoverIdx !== null && hoverIdx !== i && 'opacity-50',
                  )}
                />
                <text
                  x={bar.x + bar.width / 2}
                  y={plot.y0 + 14}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[10px]"
                >
                  {bar.label}
                </text>
              </g>
            );
          })}

          {hoverIdx !== null && bars[hoverIdx] && (
            <text
              x={bars[hoverIdx].x + bars[hoverIdx].width / 2}
              y={bars[hoverIdx].y - 6}
              textAnchor="middle"
              className="fill-foreground text-[11px] font-medium"
            >
              {formatScore(sorted[hoverIdx].score)}
            </text>
          )}
        </svg>

        <p aria-live="polite" className="sr-only">
          {hovered
            ? `${hovered.model_ref}: ${formatScore(hovered.score)}`
            : ''}
        </p>
      </div>
    </section>
  );
}
