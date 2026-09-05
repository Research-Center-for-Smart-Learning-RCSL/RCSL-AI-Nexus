'use client';

import { Button } from '@/components/ui/button';
import { CopySuccessIcon } from '@/components/composed/copy-success-icon';
import { useCopyToClipboard } from '@/lib/use-copy-to-clipboard';
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
  // The restart-per-copy and the unmount cleanup this used to hold itself now
  // live in the hook, which is where the other two call sites were missing
  // them. Failure is ignored here on purpose: the snippet is on screen and
  // selectable, so a refused clipboard needs no message.
  const { copied, copy } = useCopyToClipboard();

  return (
    <div className={cn('relative', className)}>
      <pre className="overflow-x-auto rounded-lg bg-muted p-3 pr-12 font-mono text-xs leading-relaxed">
        {code}
      </pre>
      {/* Interface, not content: `data-md-skip` keeps the button's label out of
          a Markdown export of the surrounding page, where "Copy config.toml"
          would otherwise appear as a line of prose under the snippet. */}
      <Button
        data-md-skip
        variant="ghost"
        size="xs"
        type="button"
        onClick={() => void copy(code)}
        aria-label={label}
        className="absolute top-1.5 right-1.5"
      >
        <CopySuccessIcon copied={copied} className="size-3" />
      </Button>
      <span aria-live="polite" className="sr-only">
        {copied ? 'Copied to the clipboard.' : ''}
      </span>
    </div>
  );
}
