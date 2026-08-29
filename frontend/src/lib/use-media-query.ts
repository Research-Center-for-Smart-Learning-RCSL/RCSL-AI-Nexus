'use client';

import { useEffect, useLayoutEffect, useState } from 'react';

/**
 * Layout effect on the client, plain effect during server rendering, where
 * useLayoutEffect warns and cannot run anyway.
 */
export const useIsomorphicLayoutEffect =
  typeof window === 'undefined' ? useEffect : useLayoutEffect;

/** Null until the browser has answered; server rendering never guesses. */
export function useMediaQuery(query: string): boolean | null {
  const [matches, setMatches] = useState<boolean | null>(null);

  // A layout effect, not a plain one: the entry curtains decide whether to
  // mount from this value, and a post-paint answer let the page show for a
  // frame before the curtain covered it.
  useIsomorphicLayoutEffect(() => {
    if (typeof window.matchMedia !== 'function') {
      setMatches(false);
      return;
    }

    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', update);
      return () => media.removeEventListener('change', update);
    }
    // Safari <14 exposes only the deprecated pair; skipping subscription there
    // froze the value at its first answer.
    media.addListener(update);
    return () => media.removeListener(update);
  }, [query]);

  return matches;
}
