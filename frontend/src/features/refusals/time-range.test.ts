import { describe, expect, it } from 'vitest';

import { PRESETS, toInstant, toLocalInput } from '@/features/refusals/time-range';

/**
 * The window, between the box a reader types in and the instant the API is
 * asked for.
 *
 * The backend has compared `at` against `since` and `until` since this table
 * existed and nothing in the browser ever sent either, so both comparisons
 * were unreachable — a working filter to anyone reading the SQL, and no filter
 * at all to the person the screen was built for.
 */

function preset(id: string) {
  const found = PRESETS.find((p) => p.id === id);
  if (!found) throw new Error(`no preset ${id}`);
  return found;
}

describe('toLocalInput', () => {
  it('writes the reader’s own clock, not UTC', () => {
    /**
     * The short way to do this is `date.toISOString().slice(0, 16)`, and it is
     * wrong everywhere except Greenwich: that string is UTC, so an evening in
     * Taipei fills the box with the following morning and an evening in
     * Chicago fills it with the same. The box is `datetime-local` — it means
     * local — so the value has to be built out of the local fields.
     */
    const evening = new Date(2026, 7, 17, 19, 16);

    expect(toLocalInput(evening)).toBe('2026-08-17T19:16');
  });

  it('pads every field, because the input parses nothing else', () => {
    expect(toLocalInput(new Date(2026, 0, 2, 3, 4))).toBe('2026-01-02T03:04');
  });
});

describe('toInstant', () => {
  it('is undefined for an empty box, so no filter is sent', () => {
    expect(toInstant('')).toBeUndefined();
  });

  it('is undefined for a half-typed date', () => {
    // `datetime-local` fires on the way to a valid value. Sending `2026-08-`
    // as a filter returns nothing, and an empty table reads as "there is
    // nothing there" rather than as "you are still typing".
    // `new Date('2026-08-')` is not `NaN` — it is the first of August — so a
    // parse check alone lets a partial date through as a real filter.
    expect(toInstant('2026-08-')).toBeUndefined();
    expect(toInstant('2026-08-17')).toBeUndefined();
    expect(toInstant('not a date')).toBeUndefined();
    // Right shape, not a real time.
    expect(toInstant('2026-02-31T25:00')).toBeUndefined();
  });

  it('sends the instant that local time actually names', () => {
    const local = '2026-08-17T19:16';

    expect(toInstant(local)).toBe(new Date(local).toISOString());
  });

  it('round-trips with toLocalInput to the minute the reader chose', () => {
    const chosen = new Date(2026, 7, 17, 19, 16);

    expect(toInstant(toLocalInput(chosen))).toBe(chosen.toISOString());
  });
});

describe('the presets', () => {
  const now = new Date(2026, 7, 18, 9, 30);

  it('counts an hour back from now', () => {
    expect(toLocalInput(preset('hour').from(now))).toBe('2026-08-18T08:30');
  });

  it('means the day the reader is having, not the last twenty-four hours', () => {
    // Local midnight. "Today" is a word about a calendar day, and this
    // platform is one deployment in one place.
    expect(toLocalInput(preset('today').from(now))).toBe('2026-08-18T00:00');
    expect(toLocalInput(preset('day').from(now))).toBe('2026-08-17T09:30');
  });

  it('counts seven days back rather than to the start of one', () => {
    expect(toLocalInput(preset('week').from(now))).toBe('2026-08-11T09:30');
  });

  it('produces a boundary that stays put', () => {
    /**
     * A preset writes an instant into the box and stops. The alternative — a
     * live "last hour" — moves the boundary under a reader paging through what
     * it matched, so an offset computed against one window returns rows that
     * were on the previous page of another. The freezing is the feature.
     */
    const first = preset('hour').from(now);
    const later = preset('hour').from(new Date(now.getTime() + 60_000));

    expect(first.getTime()).not.toBe(later.getTime());
    // ...which is why the screen keeps the *value*, not the preset.
    expect(toLocalInput(first)).toBe('2026-08-18T08:30');
  });
});
