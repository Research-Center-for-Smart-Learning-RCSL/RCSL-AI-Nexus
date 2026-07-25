/**
 * Pure geometry for the SVG charts, separated from the component so the scaling
 * and path building can be tested without a DOM. No library: the charts are
 * simple time series, and a dependency here would be a supply-chain surface for
 * axes and tooltips we can draw ourselves (frontend.md section 7).
 */

export type ChartPoint = { t: string; v: number };
export type ChartSeries = { label: string; points: ChartPoint[] };

export type Extent = { minT: number; maxT: number; maxV: number };

/** The data domain across every series. `maxV` is never below 1, so an all-zero
 * window still gives the y-axis a height rather than dividing by zero. */
export function extentOf(series: ChartSeries[]): Extent {
  let minT = Infinity;
  let maxT = -Infinity;
  let maxV = 0;
  for (const s of series) {
    for (const p of s.points) {
      const t = Date.parse(p.t);
      if (Number.isNaN(t)) continue;
      if (t < minT) minT = t;
      if (t > maxT) maxT = t;
      if (p.v > maxV) maxV = p.v;
    }
  }
  if (!Number.isFinite(minT)) {
    minT = 0;
    maxT = 0;
  }
  return { minT, maxT, maxV: Math.max(1, maxV) };
}

/** Round a maximum up to a readable axis bound (1, 2, 5 x 10^n). */
export function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

export type Plot = {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  extent: Extent;
  axisMax: number;
};

/** The inner plotting rectangle, with margins for the axis labels. */
export function plotArea(
  series: ChartSeries[],
  width: number,
  height: number,
  margin: { top: number; right: number; bottom: number; left: number },
): Plot {
  const extent = extentOf(series);
  return {
    x0: margin.left,
    y0: height - margin.bottom,
    x1: width - margin.right,
    y1: margin.top,
    extent,
    axisMax: niceCeil(extent.maxV),
  };
}

export function scaleX(t: number, plot: Plot): number {
  const { minT, maxT } = plot.extent;
  if (maxT === minT) return (plot.x0 + plot.x1) / 2;
  return plot.x0 + ((t - minT) / (maxT - minT)) * (plot.x1 - plot.x0);
}

export function scaleY(v: number, plot: Plot): number {
  return plot.y0 - (v / plot.axisMax) * (plot.y0 - plot.y1);
}

type XY = { x: number; y: number };

function projected(points: ChartPoint[], plot: Plot): XY[] {
  return points
    .map((p) => ({ t: Date.parse(p.t), v: p.v }))
    .filter((p) => !Number.isNaN(p.t))
    .sort((a, b) => a.t - b.t)
    .map((p) => ({ x: scaleX(p.t, plot), y: scaleY(p.v, plot) }));
}

export function linePath(points: ChartPoint[], plot: Plot): string {
  const xy = projected(points, plot);
  if (xy.length === 0) return '';
  return xy.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
}

/** A closed area from the line down to the baseline, for the single-series case. */
export function areaPath(points: ChartPoint[], plot: Plot): string {
  const xy = projected(points, plot);
  if (xy.length === 0) return '';
  const line = xy.map((p) => `L${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
  const first = xy[0];
  const last = xy[xy.length - 1];
  return `M${first.x.toFixed(2)},${plot.y0.toFixed(2)} ${line} L${last.x.toFixed(2)},${plot.y0.toFixed(2)} Z`;
}
