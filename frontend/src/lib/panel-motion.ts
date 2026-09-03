'use client';

import { useEffect, useRef, useState } from 'react';

/** The shared, deliberately short state-change duration for shell panels. */
export const PANEL_MOTION_MS = 180;

type PanelMotion = {
  /** Keep the element in the DOM while its closing transform is visible. */
  mounted: boolean;
  /** The visual target used by the CSS transition. */
  state: 'open' | 'closed';
  /** Close-start is the accessibility boundary, not animation completion. */
  closing: boolean;
};

/**
 * Separates a panel's logical state from its visual lifetime.
 *
 * A timer is intentional: transition events are optional browser rendering
 * details (and do not fire under reduced motion or an interrupted transition),
 * so neither semantics nor cleanup may depend on one arriving.
 */
export function usePanelMotion(
  open: boolean,
  reducedMotion: boolean | null,
  onExited?: () => void,
): PanelMotion {
  const [mounted, setMounted] = useState(open);
  const [state, setState] = useState<'open' | 'closed'>(open ? 'open' : 'closed');
  const exited = useRef(onExited);
  exited.current = onExited;

  // Treat an as-yet unknown preference as reduced. That avoids inventing a
  // visible interval during hydration for someone who has asked for none.
  const immediate = reducedMotion !== false;

  useEffect(() => {
    let frame: number | undefined;
    let timeout: number | undefined;

    if (open) {
      setMounted(true);
      if (immediate) {
        setState('open');
      } else {
        // Starting from the closed transform gives a newly mounted panel a
        // real origin rather than a transition from its already-open layout.
        setState('closed');
        frame = window.requestAnimationFrame(() => setState('open'));
      }
    } else if (mounted) {
      setState('closed');
      if (immediate) {
        setMounted(false);
        exited.current?.();
      } else {
        timeout = window.setTimeout(() => {
          setMounted(false);
          exited.current?.();
        }, PANEL_MOTION_MS);
      }
    }

    return () => {
      if (frame !== undefined) window.cancelAnimationFrame(frame);
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [open, immediate, mounted]);

  return { mounted, state, closing: mounted && !open };
}
