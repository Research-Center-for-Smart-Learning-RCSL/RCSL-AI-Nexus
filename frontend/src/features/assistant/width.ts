/** The assistant panel's width preference, shared by the panel and the shell.
 *
 * Two consumers, one fact. The panel sets its own width; the shell reserves the
 * matching padding so the content sits beside the panel rather than under it.
 * If those two disagreed the panel would cover exactly the thing it was widened
 * to be read next to, so the key and the event live here rather than being
 * spelled twice.
 */

export const WIDTH_KEY = 'nexus.assistant.width';
export const WIDTH_EVENT = 'nexus:assistant-width';

/** Tailwind's `max-w-sm` and `max-w-2xl`, as the padding that matches them. */
export const RESERVED_CLASS = {
  narrow: 'lg:pr-96',
  wide: 'lg:pr-[42rem]',
} as const;

export function readWidePreference(): boolean {
  if (typeof window === 'undefined') return false;
  return window.localStorage.getItem(WIDTH_KEY) === 'wide';
}
