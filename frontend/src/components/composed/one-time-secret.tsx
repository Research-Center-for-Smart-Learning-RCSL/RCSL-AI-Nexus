'use client';

/**
 * Not in the frontend.md section 2 list, added because three separate flows
 * show a value that the server will never return again (invitation link, API
 * key plaintext, recovery codes) and each of them must force an explicit
 * acknowledgement. Duplicating that in three places is how one of them ends up
 * missing the confirmation.
 */

import { useState, type ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { CopySuccessIcon } from '@/components/composed/copy-success-icon';
import { useCopyToClipboard } from '@/lib/use-copy-to-clipboard';
import { cn } from '@/lib/utils';

export type OneTimeSecretProps = {
  title: string;
  description?: ReactNode;
  /** One line per entry. Recovery codes pass ten. */
  values: string[];
  /** Wording of the acknowledgement checkbox. */
  acknowledgement?: string;
  onAcknowledgedChange?: (acknowledged: boolean) => void;
  className?: string;
};

export function OneTimeSecret({
  title,
  description,
  values,
  acknowledgement = 'I have saved these',
  onAcknowledgedChange,
  className,
}: OneTimeSecretProps) {
  // `failed` is why this screen needed the shared hook to carry one. A refused
  // clipboard used to be silent here — the button stayed reading "Copy" and
  // nothing else changed — and on the one screen where the value will never be
  // shown again, that is somebody ticking the acknowledgement and closing the
  // dialog holding nothing. The unmount cleanup arrives with it: this sits in a
  // dialog that can be dismissed inside the two seconds.
  const { copied, failed: copyFailed, copy } = useCopyToClipboard();
  const [acknowledged, setAcknowledged] = useState(false);

  return (
    <div className={cn('space-y-3', className)}>
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        {description ? (
          <p className="text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>

      <div className="rounded-lg bg-muted p-3">
        <pre className="overflow-x-auto font-mono text-xs break-all whitespace-pre-wrap select-all">
          {values.join('\n')}
        </pre>
      </div>

      <div className="flex items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(event) => {
              setAcknowledged(event.target.checked);
              onAcknowledgedChange?.(event.target.checked);
            }}
          />
          {acknowledgement}
        </label>
        <Button variant="outline" size="sm" onClick={() => void copy(values.join('\n'))} type="button">
          <CopySuccessIcon copied={copied} className="size-3.5" />
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>

      {/* Announced, not just shown: the acknowledgement checkbox above is the
          next thing in reading order and it gates dismissing the only copy. */}
      <p aria-live="polite" className="sr-only">
        {copied ? 'Copied to the clipboard.' : ''}
      </p>
      {copyFailed ? (
        <p role="alert" className="text-sm text-destructive">
          Could not reach the clipboard — the browser refused it. Select the
          text above and copy it manually before continuing.
        </p>
      ) : null}
    </div>
  );
}
