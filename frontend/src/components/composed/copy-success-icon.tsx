import { CheckIcon, CopyIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * The copy state is available to assistive technology as soon as the clipboard
 * write resolves. This pair only fades the visual icon; it never delays the
 * button's label, focus, or next click behind an animation.
 */
export function CopySuccessIcon({
  copied,
  className,
}: {
  copied: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      data-copied={copied}
      className={cn('nexus-copy-feedback shrink-0', className)}
    >
      <CopyIcon data-copy-icon="copy" className="size-full" />
      <CheckIcon data-copy-icon="success" className="size-full" />
    </span>
  );
}
