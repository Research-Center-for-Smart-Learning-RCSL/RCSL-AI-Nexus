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
  const [acknowledged, setAcknowledged] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(values.join('\n'));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied; the value is selectable on screen.
      setCopied(false);
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
    </div>
  );
}
