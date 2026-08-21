'use client';

/**
 * Keeps a scrolling transcript pinned to its newest content.
 *
 * A streaming reply grows outside the render cycle: the tokens arrive on an
 * external store, so the component holding the scroll container does not
 * re-render as the text lengthens and an effect keyed on message count never
 * fires. Growth is therefore observed on the element rather than inferred from
 * state, which also covers the cases a message count would miss — markdown
 * reflowing, a reasoning block expanding, a late web font.
 *
 * Following is conditional on the reader being at the bottom already. Scrolling
 * up is a deliberate act, and a transcript that drags the reader back to the
 * end while they are reading earlier output is worse than one that never
 * follows at all. `pinned` reports which state applies, so a caller can offer a
 * way back.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * How far from the end still counts as being at the end. A reader who has not
 * deliberately scrolled away can still sit a line or two short of the bottom
 * after a reflow, and treating that as "scrolled up" would stop the follow for
 * no reason the reader could see.
 */
const NEAR_BOTTOM_PX = 64;

export type StickToBottom = {
  /** Goes on the scrolling element. */
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** Goes on the single child whose height changes as content arrives. */
  contentRef: React.RefObject<HTMLDivElement | null>;
  /** Goes on the scrolling element's `onScroll`. */
  onScroll: () => void;
  /** False once the reader has scrolled away from the end. */
  pinned: boolean;
  scrollToBottom: (behavior?: ScrollBehavior) => void;
};

export function useStickToBottom(): StickToBottom {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  // Mirrored in a ref because the ResizeObserver below runs outside React and
  // would otherwise close over the value from the render that registered it.
  const pinnedRef = useRef(true);
  const [pinned, setPinned] = useState(true);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const container = containerRef.current;
    if (!container) return;
    // `scrollTo` does not consult the reduced-motion preference the way the CSS
    // property does, so the check is made here rather than assumed.
    const still =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    container.scrollTo({
      top: container.scrollHeight,
      behavior: still ? 'auto' : behavior,
    });
    pinnedRef.current = true;
    setPinned(true);
  }, []);

  const onScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const distance =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    const next = distance <= NEAR_BOTTOM_PX;
    pinnedRef.current = next;
    setPinned((current) => (current === next ? current : next));
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    const content = contentRef.current;
    // Absent under jsdom, where there is no layout to observe and nothing to
    // follow.
    if (!container || !content || typeof ResizeObserver === 'undefined') return;

    const observer = new ResizeObserver(() => {
      if (!pinnedRef.current) return;
      // Assigned rather than animated: this fires on every token, and a smooth
      // scroll started before the previous one finished never reaches the end.
      container.scrollTop = container.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, []);

  return { containerRef, contentRef, onScroll, pinned, scrollToBottom };
}
