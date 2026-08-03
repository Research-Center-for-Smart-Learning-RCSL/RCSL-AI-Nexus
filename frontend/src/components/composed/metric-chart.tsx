'use client';

/**
 * A small SVG time-series chart, no charting library (frontend.md section 7).
 * The data these screens show is simple magnitude-over-time, and drawing it
 * directly keeps axes and tooltips off the supply chain and lets the series
 * colours read the theme's computed ramp (--chart-1..5) so they follow light and
 * dark without a second palette.
 *
 * One series renders as a filled area; several render as plain lines with a
 * legend, since overlapping fills would be unreadable. Geometry lives in
 * chart-geometry.ts so it can be tested without a DOM.
 */

import { useRef, useState } from 'react';

import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  areaPath,
  linePath,
  plotArea,
  scaleX,
  scaleY,
  type ChartSeries,
} from '@/components/composed/chart-geometry';

export type MetricSeries = ChartSeries;

export type MetricChartProps = {
  title: string;
  series?: MetricSeries[];
  isLoading?: boolean;
  /** Formats the y-axis and tooltip numbers. Defaults to a grouped integer. */
  formatValue?: (value: number) => string;
  className?: string;
};

const VIEW_W = 640;
const VIEW_H = 220;
const MARGIN = { top: 12, right: 16, bottom: 26, left: 44 };
const DAY_MS = 86_400_000;

// currentColor picks these up, so a line's colour is set by the group's text-*
// class and follows the theme rather than a hardcoded hex.
const SERIES_COLOR = [
  'text-chart-1',
  'text-chart-2',
  'text-chart-3',
  'text-chart-4',
  'text-chart-5',
];

const defaultFormat = (value: number) => value.toLocaleString();

function tickLabel(t: number, spanMs: number): string {
  const d = new Date(t);
  if (spanMs <= 2 * DAY_MS) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function fullLabel(t: number, spanMs: number): string {
  const d = new Date(t);
  if (spanMs <= 2 * DAY_MS) {
    return d.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

type HoverState = { t: number; leftPct: number };

export function MetricChart({
  title,
  series,
  isLoading = false,
  formatValue = defaultFormat,
  className,
}: MetricChartProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hover, setHover] = useState<HoverState | null>(null);

  const withData = (series ?? []).filter((s) => s.points.length > 0);
  const hasData = withData.length > 0;

  const plot = plotArea(withData, VIEW_W, VIEW_H, MARGIN);
  const spanMs = plot.extent.maxT - plot.extent.minT;
  const single = withData.length === 1;

  // Every distinct timestamp, for the x ticks and for snapping the hover.
  const times = Array.from(
    new Set(withData.flatMap((s) => s.points.map((p) => Date.parse(p.t)))),
  )
    .filter((n) => !Number.isNaN(n))
    .sort((a, b) => a - b);

  const xTicks = times.length <= 4 ? times : [times[0], times[Math.floor(times.length / 2)], times[times.length - 1]];

  function hoverAt(index: number) {
    const t = times[Math.min(times.length - 1, Math.max(0, index))];
    if (t === undefined) return;
    setHover({ t, leftPct: (scaleX(t, plot) / VIEW_W) * 100 });
  }

  function onMove(event: React.PointerEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg || times.length === 0) return;
    const rect = svg.getBoundingClientRect();
    const vbX = ((event.clientX - rect.left) / rect.width) * VIEW_W;
    let nearest = times[0];
    let best = Infinity;
    for (const t of times) {
      const dist = Math.abs(scaleX(t, plot) - vbX);
      if (dist < best) {
        best = dist;
        nearest = t;
      }
    }
    setHover({ t: nearest, leftPct: (scaleX(nearest, plot) / VIEW_W) * 100 });
  }

  /**
   * The same readout, from the keyboard.
   *
   * Values were reachable only by hovering a pointer over the plot, so the
   * numbers behind the line were unavailable to anyone navigating by keyboard —
   * and the shape of a line is not a substitute for the figure when the question
   * is how many requests arrived at four in the morning.
   */
  function onKeyDown(event: React.KeyboardEvent<SVGSVGElement>) {
    if (times.length === 0) return;
    const current = hover ? times.indexOf(hover.t) : -1;

    switch (event.key) {
      case 'ArrowRight':
        hoverAt(current < 0 ? 0 : current + 1);
        break;
      case 'ArrowLeft':
        hoverAt(current < 0 ? times.length - 1 : current - 1);
        break;
      case 'Home':
        hoverAt(0);
        break;
      case 'End':
        hoverAt(times.length - 1);
        break;
      case 'Escape':
        setHover(null);
        return;
      default:
        return;
    }
    // Only for the keys handled above, so Tab still moves on and the page still
    // scrolls with the arrows when the chart is not the focused element.
    event.preventDefault();
  }

  const hoverEntries = hover
    ? withData.map((s, i) => {
        const point = s.points.find((p) => Date.parse(p.t) === hover.t);
        return { label: s.label, color: SERIES_COLOR[i % SERIES_COLOR.length], value: point?.v };
      })
    : [];

  return (
    <Card className={cn('h-full', className)}>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        {!single && hasData ? (
          <div className="flex flex-wrap justify-end gap-x-3 gap-y-1">
            {withData.map((s, i) => (
              <span key={s.label} className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <span className={cn('size-2 rounded-full bg-current', SERIES_COLOR[i % SERIES_COLOR.length])} />
                {s.label}
              </span>
            ))}
          </div>
        ) : null}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="h-48 animate-pulse rounded-lg bg-muted" />
        ) : !hasData ? (
          <div className="flex h-48 items-center justify-center rounded-lg border border-dashed text-center text-xs text-muted-foreground">
            No activity in this range.
          </div>
        ) : (
          <div className="relative">
            <svg
              ref={svgRef}
              viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
              className="h-48 w-full touch-none rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              role="img"
              aria-label={`${title} over time. ${times.length} points. Focus and use the arrow keys to read values.`}
              tabIndex={0}
              onPointerMove={onMove}
              onPointerLeave={() => setHover(null)}
              onKeyDown={onKeyDown}
              onBlur={() => setHover(null)}
            >
              {/* Baseline and the top gridline, with their value labels. */}
              {[0, plot.axisMax].map((v) => {
                const y = scaleY(v, plot);
                return (
                  <g key={v}>
                    <line
                      x1={plot.x0}
                      x2={plot.x1}
                      y1={y}
                      y2={y}
                      className="stroke-border"
                      strokeWidth={1}
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

              {/* X-axis time ticks. */}
              {xTicks.map((t) => (
                <text
                  key={t}
                  x={scaleX(t, plot)}
                  y={plot.y0 + 16}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[10px]"
                >
                  {tickLabel(t, spanMs)}
                </text>
              ))}

              {withData.map((s, i) => (
                <g key={s.label} className={SERIES_COLOR[i % SERIES_COLOR.length]}>
                  {single ? (
                    <path d={areaPath(s.points, plot)} className="fill-current opacity-15" />
                  ) : null}
                  <path
                    d={linePath(s.points, plot)}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                  />
                </g>
              ))}

              {/* Hover guide and the point markers. */}
              {hover ? (
                <g>
                  <line
                    x1={scaleX(hover.t, plot)}
                    x2={scaleX(hover.t, plot)}
                    y1={plot.y1}
                    y2={plot.y0}
                    className="stroke-muted-foreground/40"
                    strokeWidth={1}
                  />
                  {hoverEntries.map((entry, i) =>
                    entry.value === undefined ? null : (
                      <circle
                        key={entry.label}
                        cx={scaleX(hover.t, plot)}
                        cy={scaleY(entry.value, plot)}
                        r={3}
                        className={cn('fill-current', SERIES_COLOR[i % SERIES_COLOR.length])}
                      />
                    ),
                  )}
                </g>
              ) : null}
            </svg>

            {/* The tooltip's contents as text. The tooltip itself is positioned
                and pointer-driven, so it is not something a screen reader can
                be walked through; this says the same thing when the selection
                moves, by pointer or by arrow key. */}
            <p aria-live="polite" className="sr-only">
              {hover
                ? `${fullLabel(hover.t, spanMs)}. ${hoverEntries
                    .map(
                      (entry) =>
                        `${entry.label}: ${
                          entry.value === undefined
                            ? 'no value'
                            : formatValue(entry.value)
                        }`,
                    )
                    .join('. ')}`
                : ''}
            </p>

            {hover ? (
              <div
                className="pointer-events-none absolute top-1 z-10 -translate-x-1/2 rounded-md bg-popover px-2 py-1 text-xs text-popover-foreground shadow ring-1 ring-foreground/10"
                style={{ left: `${Math.min(88, Math.max(12, hover.leftPct))}%` }}
              >
                <div className="mb-0.5 font-medium">{fullLabel(hover.t, spanMs)}</div>
                {hoverEntries.map((entry) => (
                  <div key={entry.label} className="flex items-center gap-1.5">
                    <span className={cn('size-2 rounded-full bg-current', entry.color)} />
                    <span className="text-muted-foreground">{entry.label}</span>
                    <span className="ml-auto tabular-nums">
                      {entry.value === undefined ? '-' : formatValue(entry.value)}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
