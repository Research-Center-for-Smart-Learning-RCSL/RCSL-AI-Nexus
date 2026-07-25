import { describe, expect, it } from 'vitest';

import {
  areaPath,
  extentOf,
  linePath,
  niceCeil,
  plotArea,
  scaleX,
  scaleY,
  type ChartSeries,
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
