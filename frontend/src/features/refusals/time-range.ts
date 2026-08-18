/**
 * The window a refusal happened in, as the screen holds it and as the server
 * wants it.
 *
 * **This screen's question is "what happened at 19:16?"** — that sentence is in
 * the page's own explanation, and it was answered by an administrator reading
 * container logs because there was no window to ask for. The backend has
 * filtered on `since`/`until` since the table existed; nothing in the browser
 * ever sent either, so the comparison was unreachable and read as a working
 * filter to anyone looking at the SQL.
 *
 * **A preset fills the boxes rather than replacing them.** "Last hour" writes
 * an instant into `from` and leaves it there, so the reader can see what it
 * meant and then move it. The alternative — a mode where "last hour" stays
 * live — is worse here in two ways: the boundary would slide under a reader
 * paging through results, and offsets computed against a moving window return
 * rows that were on the previous page. A frozen boundary is what an
 * investigation wants.
 *
 * The half-open shape is the backend's (`at >= since`, `at < until`) and is
 * carried through to the labels rather than smoothed over, which is why the
 * controls say "From" and "Before".
 */

export type Preset = { id: string; label: string; from: (now: Date) => Date };

export const PRESETS: Preset[] = [
  {
    id: 'hour',
    label: 'Last hour',
    from: (now) => new Date(now.getTime() - 60 * 60 * 1000),
  },
  {
    id: 'day',
    label: 'Last 24 hours',
    from: (now) => new Date(now.getTime() - 24 * 60 * 60 * 1000),
  },
  {
    id: 'today',
    // Local midnight, not the last 24 hours: "today" is the word people use
    // about the day they are having, and this platform is one deployment in
    // one place.
    label: 'Today',
    from: (now) => new Date(now.getFullYear(), now.getMonth(), now.getDate()),
  },
  {
    id: 'week',
    label: 'Last 7 days',
    from: (now) => new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000),
  },
];

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

/**
 * A `Date` as `<input type="datetime-local">` wants it: `YYYY-MM-DDTHH:mm`, in
 * the reader's own zone.
 *
 * Built field by field rather than by slicing `toISOString()`, which is the
 * short version of this and is wrong: that string is UTC, so west of Greenwich
 * it fills the box with yesterday.
 */
export function toLocalInput(date: Date): string {
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** Exactly what `datetime-local` emits, seconds optional. */
const LOCAL = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/;

/**
 * What the box holds, as the instant the API is asked for.
 *
 * `undefined` for empty, and for a half-typed value: `datetime-local` fires on
 * every keystroke, so `2026-08-` arrives on the way to a real date and must not
 * be sent as a filter — the query would return nothing and read as "there is
 * nothing there".
 *
 * **The shape is checked before parsing, because `Date` will not reject it.**
 * `new Date('2026-08-')` is not `NaN`; it is the first of August, so a `NaN`
 * guard alone silently filters to a month nobody asked for while somebody is
 * still typing the day. Parsing stays as the second check, for a value that is
 * the right shape and not a real time — `2026-02-31T25:00`.
 *
 * Parsed without a zone on purpose: a `YYYY-MM-DDTHH:mm` string with no `Z` is
 * local time by specification, which is what the box means and what the reader
 * typed.
 */
export function toInstant(local: string): string | undefined {
  if (!LOCAL.test(local)) return undefined;
  const parsed = new Date(local);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
}
