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
 *
 * **The refs are callbacks, not ref objects, and that is load-bearing.** The
 * assistant drawer renders nothing at all while it is closed, so an effect that
 * read `ref.current` once at mount found two nulls, returned, and never ran
 * again — the observer was never attached for the one caller that mounts
 * before its own elements exist. Attaching from the ref callback ties the
 * observer to the elements arriving rather than to the component mounting, and
 * a `ResizeObserver` delivers an initial observation when it begins, so a
 * drawer reopened on an existing conversation lands at the end of it.
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
  containerRef: (node: HTMLDivElement | null) => void;
  /** Goes on the single child whose height changes as content arrives. */
  contentRef: (node: HTMLDivElement | null) => void;
  /** Goes on the scrolling element's `onScroll`. */
  onScroll: () => void;
  /** False once the reader has scrolled away from the end. */
  pinned: boolean;
  scrollToBottom: () => void;
};

export function useStickToBottom(): StickToBottom {
  const container = useRef<HTMLDivElement | null>(null);
  const content = useRef<HTMLDivElement | null>(null);
  const observer = useRef<ResizeObserver | null>(null);
  // Mirrored in a ref because the ResizeObserver below runs outside React and
  // would otherwise close over the value from the render that registered it.
  const pinnedRef = useRef(true);
  const [pinned, setPinned] = useState(true);

  const follow = useCallback(() => {
    const element = container.current;
    if (!element) return;
    // Assigned rather than animated, everywhere. This runs on every token, and
    // a smooth scroll started before the previous one finished never reaches
    // the end; worse, the intermediate `scroll` events an animation emits are
    // indistinguishable from a reader scrolling up, so an animated jump would
    // unpin itself part way and stop following the reply it was catching up to.
    element.scrollTop = element.scrollHeight;
  }, []);

  const observe = useCallback(() => {
    observer.current?.disconnect();
    observer.current = null;
    // ResizeObserver is absent under jsdom, where there is no layout to observe
    // and nothing to follow.
    if (!container.current || !content.current) return;
    if (typeof ResizeObserver === 'undefined') return;
    const next = new ResizeObserver(() => {
      if (pinnedRef.current) follow();
    });
    next.observe(content.current);
    observer.current = next;
  }, [follow]);

  const containerRef = useCallback(
    (node: HTMLDivElement | null) => {
      container.current = node;
      observe();
    },
    [observe],
  );

  const contentRef = useCallback(
    (node: HTMLDivElement | null) => {
      content.current = node;
      observe();
    },
    [observe],
  );

  useEffect(() => () => observer.current?.disconnect(), []);

  const scrollToBottom = useCallback(() => {
    follow();
    pinnedRef.current = true;
    setPinned(true);
  }, [follow]);

  const onScroll = useCallback(() => {
    const element = container.current;
    if (!element) return;
    const distance =
      element.scrollHeight - element.scrollTop - element.clientHeight;
    const next = distance <= NEAR_BOTTOM_PX;
    pinnedRef.current = next;
    setPinned((current) => (current === next ? current : next));
  }, []);

  return { containerRef, contentRef, onScroll, pinned, scrollToBottom };
}
