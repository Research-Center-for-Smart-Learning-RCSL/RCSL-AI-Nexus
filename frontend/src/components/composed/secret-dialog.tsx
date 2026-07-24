'use client';

import type { ReactNode } from 'react';

import { Dialog, DialogContent } from '@/components/ui/dialog';

/**
 * A dialog that cannot be dismissed by accident while it is showing something
 * that exists exactly once.
 *
 * The plain dialog closes on Escape, on an outside click, and on the corner X.
 * For an API key plaintext, an invitation link, or a set of recovery codes,
 * every one of those destroys the only copy: the server keeps a peppered hash
 * and nothing else. Pressing Escape to dismiss what looks like a modal is a
 * completely ordinary thing to do.
 *
 * So while `locked` holds, the three implicit dismissals are disabled and the
 * only way out is a deliberate control the caller renders.
 */
export function SecretDialog({
  open,
  onOpenChange,
  locked,
  className,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** True while an unrecoverable secret is on screen. */
  locked: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // `open` is controlled by the caller, so declining to propagate a
        // close request is what actually keeps the dialog on screen. Escape
        // and an outside click both arrive here and both are ignored while
        // locked; the corner X is removed as well so there is no control that
        // silently discards the secret.
        if (locked && !next) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className={className} showCloseButton={!locked}>
        {children}
      </DialogContent>
    </Dialog>
  );
}
