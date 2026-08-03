'use client';

/**
 * Not in the frontend.md section 2 list, added because three separate flows
 * show a value that the server will never return again (invitation link, API
 * key plaintext, recovery codes) and each of them must force an explicit
 * acknowledgement. Duplicating that in three places is how one of them ends up
 * missing the confirmation.
 */

import { useState, type ReactNode } from 'react';
import { CheckIcon, CopyIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
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
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  async function copy() {
    setCopyFailed(false);
    try {
      await navigator.clipboard.writeText(values.join('\n'));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied — an insecure origin, or a browser
      // permission — and the failure used to be silent: the button stayed
      // reading "Copy" and nothing else changed. On the one screen where the
      // value will never be shown again, that is someone ticking the
      // acknowledgement and closing the dialog holding nothing.
      setCopied(false);
      setCopyFailed(true);
    }
  }

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
        <Button variant="outline" size="sm" onClick={copy} type="button">
          {copied ? <CheckIcon /> : <CopyIcon />}
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
          Could not reach the clipboard — your browser refused it. Select the
          text above and copy it manually before continuing.
        </p>
      ) : null}
    </div>
  );
}
