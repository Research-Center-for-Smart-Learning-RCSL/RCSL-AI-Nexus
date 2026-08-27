'use client';

import { useMediaQuery } from '@/lib/use-media-query';

/** Null until the browser preference is known; server rendering never guesses. */
export function useReducedMotion(): boolean | null {
  return useMediaQuery('(prefers-reduced-motion: reduce)');
}
