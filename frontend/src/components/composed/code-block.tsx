'use client';

import { useEffect, useRef, useState } from 'react';
import { CheckIcon, CopyIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * A snippet meant to be copied rather than read.
 *
 * Scrolls horizontally inside itself rather than wrapping: a wrapped shell
 * command looks like several commands, and a wrapped line in a dialog is how
 * somebody pastes half of one.
 */
export function CodeBlock({
  code,
  className,
  label = 'Copy',
}: {
  code: string;
  className?: string;
  /** Named when there is more than one block in view. */
  label?: string;
}) {
  const [copied, setCopied] = useState(false);
  // Held so each copy restarts the two seconds rather than inheriting what was
  // left of the previous one, and so the dialog this usually sits in can be
  // dismissed inside that window without the timer firing on a dead component.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied; the text is selectable on screen.
      setCopied(false);
    }
  }

  return (
    <div className={cn('relative', className)}>
      <pre className="overflow-x-auto rounded-lg bg-muted p-3 pr-12 font-mono text-xs leading-relaxed">
        {code}
      </pre>
      <Button
        variant="ghost"
        size="xs"
        type="button"
        onClick={copy}
        aria-label={label}
        className="absolute top-1.5 right-1.5"
      >
        {copied ? <CheckIcon /> : <CopyIcon />}
      </Button>
    </div>
  );
}
