'use client';

import { useCallback, useEffect, useState } from 'react';

const COLLAPSED_KEY = 'nexus.nav.collapsed';

/**
 * Which groups the reader has folded away, remembered across navigations.
 *
 * Read after mount rather than during render: this component is server-rendered
 * and `localStorage` does not exist there, so reading it inline would either
 * throw or produce markup that disagrees with the client's first paint. The
 * first render is therefore "everything open", which is also the right default
 * — a nav that starts collapsed hides the thing the reader came for, and the
 * clutter this fixes is worth one click to fold, not a hunt to unfold.
 *
 * A bad value in storage is discarded rather than repaired. It is a UI
 * preference; the cost of getting it wrong is one lost fold, and code that
 * carefully rehabilitates malformed JSON is code nobody can justify.
 */
export function useCollapsedGroups(): [Set<string>, (id: string) => void] {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      const stored: unknown = JSON.parse(
        window.localStorage.getItem(COLLAPSED_KEY) ?? '[]',
      );
      if (Array.isArray(stored)) {
        setCollapsed(new Set(stored.filter((id): id is string => typeof id === 'string')));
      }
    } catch {
      // Unparseable or unavailable storage: keep the default.
    }
  }, []);

  const toggle = useCallback((id: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      try {
        window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...next]));
      } catch {
        // Private browsing, or a full quota. The fold still works for this
        // session; only its memory is lost, which is not worth an error.
      }
      return next;
    });
  }, []);

  return [collapsed, toggle];
}
