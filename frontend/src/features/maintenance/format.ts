/** "Expected back" in the reader's own locale and time zone, or null. */
export function formatExpectedReturn(iso: string | null): string | null {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  return at.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}
