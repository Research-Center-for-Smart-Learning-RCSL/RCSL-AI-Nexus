import { describe, expect, it } from 'vitest';

import {
  areaPath,
  categoricalBarRects,
  extentOf,
  heatmapGrid,
  linePath,
  niceCeil,
  plotArea,
  scaleX,
  scaleY,
  sparklineArea,
  sparklinePath,
  yTicks,
  type ChartSeries,
  type SparkPlot,
} from '@/components/composed/chart-geometry';

const MARGIN = { top: 10, right: 10, bottom: 20, left: 40 };

function series(points: [string, number][]): ChartSeries {
  return { label: 's', points: points.map(([t, v]) => ({ t, v })) };
}

describe('extentOf', () => {
  it('spans every series and never lets the max fall to zero', () => {
    const e = extentOf([
      series([['2026-07-25T10:00:00Z', 0]]),
      series([['2026-07-25T12:00:00Z', 0]]),
    ]);
    expect(e.minT).toBe(Date.parse('2026-07-25T10:00:00Z'));
    expect(e.maxT).toBe(Date.parse('2026-07-25T12:00:00Z'));
    // An all-zero window still gives the y-axis a height rather than 0.
    expect(e.maxV).toBe(1);
  });

  it('is safe on empty input', () => {
    const e = extentOf([]);
    expect(e).toEqual({ minT: 0, maxT: 0, maxV: 1 });
  });
});

describe('niceCeil', () => {
  it('rounds up to a 1/2/5 x 10^n bound', () => {
    expect(niceCeil(1)).toBe(1);
    expect(niceCeil(3)).toBe(5);
    expect(niceCeil(7)).toBe(10);
    expect(niceCeil(42)).toBe(50);
    expect(niceCeil(120)).toBe(200);
  });

  it('never returns zero', () => {
    expect(niceCeil(0)).toBe(1);
    expect(niceCeil(-5)).toBe(1);
  });
});

describe('scales', () => {
  const s = series([
    ['2026-07-25T10:00:00Z', 0],
    ['2026-07-25T12:00:00Z', 40],
  ]);
  const plot = plotArea([s], 200, 120, MARGIN);

  it('maps the domain edges to the plot rectangle', () => {
    expect(scaleX(plot.extent.minT, plot)).toBeCloseTo(MARGIN.left);
    expect(scaleX(plot.extent.maxT, plot)).toBeCloseTo(200 - MARGIN.right);
    // Zero sits on the baseline; the axis max sits at the top margin.
    expect(scaleY(0, plot)).toBeCloseTo(120 - MARGIN.bottom);
    expect(scaleY(plot.axisMax, plot)).toBeCloseTo(MARGIN.top);
  });

  it('centres a single-point series rather than dividing by zero', () => {
    const one = plotArea([series([['2026-07-25T10:00:00Z', 5]])], 200, 120, MARGIN);
    expect(scaleX(one.extent.minT, one)).toBeCloseTo((one.x0 + one.x1) / 2);
  });
});

describe('paths', () => {
  const plot = plotArea(
    [series([['2026-07-25T10:00:00Z', 0], ['2026-07-25T12:00:00Z', 10]])],
    200,
    120,
    MARGIN,
  );

  it('a line starts with M and then draws L segments', () => {
    const d = linePath(
      [
        { t: '2026-07-25T10:00:00Z', v: 0 },
        { t: '2026-07-25T12:00:00Z', v: 10 },
      ],
      plot,
    );
    expect(d.startsWith('M')).toBe(true);
    expect(d).toContain('L');
  });

  it('an area closes back to the baseline', () => {
    const d = areaPath(
      [
        { t: '2026-07-25T10:00:00Z', v: 0 },
        { t: '2026-07-25T12:00:00Z', v: 10 },
      ],
      plot,
    );
    expect(d.endsWith('Z')).toBe(true);
  });

  it('is empty for a series with no points', () => {
    expect(linePath([], plot)).toBe('');
    expect(areaPath([], plot)).toBe('');
  });
});

describe('yTicks', () => {
  it('always includes 0 and the axis max', () => {
    for (const max of [1, 2, 5, 10, 50, 100, 200, 500]) {
      const ticks = yTicks(max);
      expect(ticks[0]).toBe(0);
      expect(ticks[ticks.length - 1]).toBe(max);
    }
  });

  it('produces at least 3 ticks for non-trivial values', () => {
    expect(yTicks(10).length).toBeGreaterThanOrEqual(3);
    expect(yTicks(50).length).toBeGreaterThanOrEqual(3);
    expect(yTicks(100).length).toBeGreaterThanOrEqual(3);
  });

  it('returns [0] for zero or negative input', () => {
    expect(yTicks(0)).toEqual([0]);
    expect(yTicks(-5)).toEqual([0]);
  });

  it('produces evenly spaced values', () => {
    const ticks = yTicks(100);
    const step = ticks[1] - ticks[0];
    for (let i = 2; i < ticks.length; i++) {
      expect(ticks[i] - ticks[i - 1]).toBeCloseTo(step);
    }
  });
});

describe('sparkline', () => {
  const spark: SparkPlot = { width: 80, height: 24, minV: 0, maxV: 10 };

  it('draws a line starting with M', () => {
    const d = sparklinePath(
      [{ t: '2026-07-25T10:00:00Z', v: 0 }, { t: '2026-07-25T12:00:00Z', v: 10 }],
      spark,
    );
    expect(d.startsWith('M')).toBe(true);
    expect(d).toContain('L');
  });

  it('closes the area path with Z', () => {
    const d = sparklineArea(
      [{ t: '2026-07-25T10:00:00Z', v: 0 }, { t: '2026-07-25T12:00:00Z', v: 10 }],
      spark,
    );
    expect(d.endsWith('Z')).toBe(true);
  });

  it('returns empty for no points', () => {
    expect(sparklinePath([], spark)).toBe('');
    expect(sparklineArea([], spark)).toBe('');
  });

  it('handles a single point without dividing by zero', () => {
    const d = sparklinePath([{ t: '2026-07-25T10:00:00Z', v: 5 }], spark);
    expect(d.startsWith('M')).toBe(true);
    expect(d).not.toContain('NaN');
  });

  it('handles all-same values with a horizontal line', () => {
    const d = sparklinePath(
      [{ t: '2026-07-25T10:00:00Z', v: 5 }, { t: '2026-07-25T12:00:00Z', v: 5 }],
      { width: 80, height: 24, minV: 5, maxV: 5 },
    );
    expect(d).not.toContain('NaN');
  });
});

describe('categoricalBarRects', () => {
  const p = plotArea([series([['2026-07-25T10:00:00Z', 100]])], 200, 120, MARGIN);

  it('produces one rect per item', () => {
    const bars = categoricalBarRects(
      [{ label: 'A', v: 50 }, { label: 'B', v: 100 }],
      p,
    );
    expect(bars).toHaveLength(2);
  });

  it('bars stay within the plot area', () => {
    const bars = categoricalBarRects(
      [{ label: 'A', v: 50 }, { label: 'B', v: 100 }, { label: 'C', v: 75 }],
      p,
    );
    for (const bar of bars) {
      expect(bar.x).toBeGreaterThanOrEqual(p.x0 - 0.01);
      expect(bar.x + bar.width).toBeLessThanOrEqual(p.x1 + 0.01);
    }
  });

  it('returns empty for no items', () => {
    expect(categoricalBarRects([], p)).toEqual([]);
  });
});

describe('heatmapGrid', () => {
  it('produces rows * cols cells', () => {
    const cells = heatmapGrid(3, 4, { x0: 0, y0: 0, width: 200, height: 120 });
    expect(cells).toHaveLength(12);
  });

  it('assigns correct row and col indices', () => {
    const cells = heatmapGrid(2, 3, { x0: 0, y0: 0, width: 100, height: 50 });
    expect(cells[0]).toMatchObject({ row: 0, col: 0 });
    expect(cells[2]).toMatchObject({ row: 0, col: 2 });
    expect(cells[3]).toMatchObject({ row: 1, col: 0 });
  });

  it('returns empty for zero dimensions', () => {
    expect(heatmapGrid(0, 5, { x0: 0, y0: 0, width: 100, height: 50 })).toEqual([]);
    expect(heatmapGrid(3, 0, { x0: 0, y0: 0, width: 100, height: 50 })).toEqual([]);
  });
});
