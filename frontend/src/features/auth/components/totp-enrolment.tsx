'use client';

/**
 * The TOTP secret is a bearer credential (security.md section 5.3). Two things
 * follow, and both are the reason this component looks the way it does:
 *
 *  - The QR image is fetched from the admin API over the same origin, never
 *    rendered by a third-party chart or QR service, which would hand the secret
 *    to someone else.
 *  - No QR library is bundled. Generating the image client-side would mean
 *    shipping a dependency purely to redraw a value the backend already holds,
 *    and the base32 secret below covers the case where the image will not load.
 */

import Image from 'next/image';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { Enrolment } from '@/features/auth/schema';

export type TotpEnrolmentProps = {
  enrolment: Enrolment;
  /** Same-origin endpoint that renders the provisioning URI as a PNG. */
  qrEndpoint: string;
  className?: string;
};

export function TotpEnrolment({
  enrolment,
  qrEndpoint,
  className,
}: TotpEnrolmentProps) {
  const [imageFailed, setImageFailed] = useState(false);
  const [showSecret, setShowSecret] = useState(false);

  return (
    <div className={cn('space-y-3', className)}>
      <div className="space-y-1">
        <p className="font-medium">Set up your authenticator</p>
        <p className="text-sm text-muted-foreground">
          Scan this with an authenticator app, then enter the six-digit code it
          shows. This step cannot be skipped.
        </p>
      </div>

      <div className="flex items-center gap-4">
        {imageFailed ? (
          <div className="flex size-40 items-center justify-center rounded-lg border border-dashed text-center text-xs text-muted-foreground">
            QR unavailable. Enter the key manually.
          </div>
        ) : (
          <Image
            src={qrEndpoint}
            alt="TOTP provisioning QR code"
            width={160}
            height={160}
            unoptimized
            className="size-40 rounded-lg bg-white p-2"
            onError={() => setImageFailed(true)}
          />
        )}

        <div className="space-y-2 text-sm">
          <p className="text-muted-foreground">Account: {enrolment.login}</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setShowSecret((shown) => !shown)}
          >
            {showSecret ? 'Hide key' : 'Enter key manually'}
          </Button>
          {showSecret ? (
            <code className="block font-mono text-xs break-all select-all">
              {enrolment.secret}
            </code>
          ) : null}
        </div>
      </div>
    </div>
  );
}
