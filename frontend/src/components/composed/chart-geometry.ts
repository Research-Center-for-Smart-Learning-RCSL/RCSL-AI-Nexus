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
type TV = { t: number; v: number };

function parseSortPoints(points: ChartPoint[]): TV[] {
  return points
    .map((p) => ({ t: Date.parse(p.t), v: p.v }))
    .filter((p) => !Number.isNaN(p.t))
    .sort((a, b) => a.t - b.t);
}

function projected(points: ChartPoint[], plot: Plot): XY[] {
  return parseSortPoints(points)
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

// ---------------------------------------------------------------------------
// Y-axis ticks
// ---------------------------------------------------------------------------

/** Intermediate Y-axis values between 0 and `axisMax`, always including both
 *  endpoints. Because `axisMax` comes from `niceCeil` (1/2/5 × 10^n), simple
 *  division into halves, quarters, or fifths always produces clean numbers. */
export function yTicks(axisMax: number): number[] {
  if (axisMax <= 0) return [0];
  let step: number;
  const mag = 10 ** Math.floor(Math.log10(axisMax));
  const norm = axisMax / mag;
  if (norm <= 1) step = mag / 5;
  else if (norm <= 2) step = mag / 2;
  else step = mag;
  if (step <= 0) return [0, axisMax];
  const ticks: number[] = [];
  for (let v = 0; v <= axisMax + step * 0.01; v += step) {
    ticks.push(Math.round(v * 1e10) / 1e10);
  }
  if (ticks[ticks.length - 1] !== axisMax) ticks.push(axisMax);
  return ticks;
}

// ---------------------------------------------------------------------------
// Sparkline geometry (no margins, no axes)
// ---------------------------------------------------------------------------

export type SparkPlot = { width: number; height: number; minV: number; maxV: number };

function sparkProject(points: ChartPoint[], spark: SparkPlot): XY[] {
  const sorted = parseSortPoints(points);
  if (sorted.length === 0) return [];
  const minT = sorted[0].t;
  const maxT = sorted[sorted.length - 1].t;
  const rangeT = maxT - minT || 1;
  const rangeV = spark.maxV - spark.minV || 1;
  return sorted.map((p) => ({
    x: ((p.t - minT) / rangeT) * spark.width,
    y: spark.height - ((p.v - spark.minV) / rangeV) * spark.height,
  }));
}

export function sparklinePath(points: ChartPoint[], spark: SparkPlot): string {
  const xy = sparkProject(points, spark);
  if (xy.length === 0) return '';
  return xy.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
}

export function sparklineArea(points: ChartPoint[], spark: SparkPlot): string {
  const xy = sparkProject(points, spark);
  if (xy.length === 0) return '';
  const line = xy.map((p) => `L${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
  const first = xy[0];
  const last = xy[xy.length - 1];
  const h = spark.height.toFixed(2);
  return `M${first.x.toFixed(2)},${h} ${line} L${last.x.toFixed(2)},${h} Z`;
}

/** A plot area for a categorical chart where the X axis is labels, not time. */
export function barPlotArea(
  width: number,
  height: number,
  margin: { top: number; right: number; bottom: number; left: number },
  axisMax: number,
): Plot {
  return {
    x0: margin.left,
    y0: height - margin.bottom,
    x1: width - margin.right,
    y1: margin.top,
    extent: { minT: 0, maxT: 0, maxV: axisMax },
    axisMax: niceCeil(axisMax),
  };
}

// ---------------------------------------------------------------------------
// Categorical bar chart geometry
// ---------------------------------------------------------------------------

export type CategoricalPoint = { label: string; v: number };
export type BarRect = { x: number; y: number; width: number; height: number; label: string; v: number };

export function categoricalBarRects(
  items: CategoricalPoint[],
  plot: Plot,
  gap = 4,
): BarRect[] {
  if (items.length === 0) return [];
  const totalW = plot.x1 - plot.x0;
  const barW = Math.max(1, (totalW - gap * (items.length - 1)) / items.length);
  return items.map((item, i) => {
    const x = plot.x0 + i * (barW + gap);
    const yTop = scaleY(item.v, plot);
    return { x, y: yTop, width: barW, height: plot.y0 - yTop, label: item.label, v: item.v };
  });
}

// ---------------------------------------------------------------------------
// Heatmap grid geometry
// ---------------------------------------------------------------------------

export type HeatCell = { x: number; y: number; width: number; height: number; row: number; col: number };

export function heatmapGrid(
  rows: number,
  cols: number,
  area: { x0: number; y0: number; width: number; height: number },
  gap = 2,
): HeatCell[] {
  if (rows <= 0 || cols <= 0) return [];
  const cellW = Math.max(1, (area.width - gap * (cols - 1)) / cols);
  const cellH = Math.max(1, (area.height - gap * (rows - 1)) / rows);
  const cells: HeatCell[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      cells.push({
        x: area.x0 + c * (cellW + gap),
        y: area.y0 + r * (cellH + gap),
        width: cellW,
        height: cellH,
        row: r,
        col: c,
      });
    }
  }
  return cells;
}
