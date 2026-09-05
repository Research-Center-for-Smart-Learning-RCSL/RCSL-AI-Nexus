'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Write text to the clipboard and say so for a moment.
 *
 * **Extracted because there were three of these and they had drifted.** The
 * behaviour is the same everywhere — write, show `Copied` for two seconds, cope
 * with a browser that refuses — but each copy had answered a different subset
 * of the three questions it raises, and the answers were not interchangeable:
 *
 * - `code-block.tsx` held the timer in a ref, restarted it per copy and cleared
 *   it on unmount. It is the one that got it right, and it is the one that
 *   lives in a dialog, where a component dismissed inside those two seconds
 *   would otherwise have a timer fire on it.
 * - `one-time-secret.tsx` did neither, and it is the one screen where the value
 *   is never shown again. It was also the only one that surfaced *failure*,
 *   which it has to: a refused clipboard there means somebody ticks "I have
 *   saved these" holding nothing.
 * - `export-markdown.tsx` kept the ref and forgot the unmount.
 *
 * So the hook owns all three: the restart, the cleanup, and a `failed` flag the
 * caller may render or ignore. What it deliberately does not own is what to say
 * about a failure — a snippet still on screen needs no message, and a secret
 * that will never be shown again needs a loud one.
 */
export function useCopyToClipboard(resetAfterMs = 2000) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(false);
  const latestRequest = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // Invalidate an in-flight clipboard write before it can resolve and
      // create a timer or update state after this component has unmounted.
      latestRequest.current += 1;
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
    };
  }, []);

  const copy = useCallback(
    async (text: string): Promise<boolean> => {
      const request = latestRequest.current + 1;
      latestRequest.current = request;
      if (!mounted.current) return false;

      // A new attempt supersedes the previous success window even while its
      // clipboard promise is pending, so an older timer cannot clear newer UI.
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
      setFailed(false);
      try {
        await navigator.clipboard.writeText(text);
        if (!mounted.current || request !== latestRequest.current) return true;
        setCopied(true);
        // Cleared first, so each copy gets the whole window rather than
        // whatever was left of the previous one.
        timer.current = setTimeout(() => {
          if (!mounted.current || request !== latestRequest.current) return;
          timer.current = null;
          setCopied(false);
        }, resetAfterMs);
        return true;
      } catch {
        // Permission refused, or an insecure origin. Never thrown onward: a
        // clipboard that will not open is not an error the page can act on,
        // and every caller has the text on screen already.
        if (mounted.current && request === latestRequest.current) {
          setCopied(false);
          setFailed(true);
        }
        return false;
      }
    },
    [resetAfterMs],
  );

  return { copied, failed, copy };
}
