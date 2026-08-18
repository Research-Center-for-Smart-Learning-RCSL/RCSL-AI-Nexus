'use client';

import { useEffect, useState } from 'react';

/**
 * A value once it has stopped changing, for a filter that costs something to
 * apply.
 *
 * **The audit log found this first.** `logs-table.tsx` carries the same wait
 * inline, with the finding written next to it: "every keystroke queried the
 * server: typing one action name sent a dozen requests, eleven of which
 * described a prefix that matches nothing by definition." The refusals screen
 * repeated it and made it more expensive, which is why the wait is a shared
 * thing now — a name search there is a `LIKE '%…%'` on an unindexed column,
 * run twice per request (the page and its `COUNT`), against an append-only
 * table every refused gateway request adds to. Twelve characters typed is
 * twenty-four scans.
 *
 * It is not only a cost question. A cross-account read writes a
 * `refusal.read_any` row per request, so an undebounced box turned one
 * question into a dozen audit rows naming each successive prefix of the name —
 * in the table whose use case explains at length why it records once per
 * request rather than once per row.
 *
 * `logs-table.tsx` keeps its own copy for now, because it also guards the page
 * offset against resetting inside the wait; this returns the settled value and
 * leaves what to do about it to the caller.
 */
export function useDebounced<T>(value: T, delayMs = 300): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return settled;
}
