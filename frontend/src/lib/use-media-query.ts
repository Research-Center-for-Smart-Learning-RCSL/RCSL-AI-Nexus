'use client';

import { useEffect, useState } from 'react';

/** Null until the browser has answered; server rendering never guesses. */
export function useMediaQuery(query: string): boolean | null {
  const [matches, setMatches] = useState<boolean | null>(null);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') {
      setMatches(false);
      return;
    }

    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, [query]);

  return matches;
}
