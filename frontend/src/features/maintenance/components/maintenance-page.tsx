'use client';

import Link from 'next/link';
import { WrenchIcon } from 'lucide-react';

import { Button, buttonVariants } from '@/components/ui/button';
import type { MaintenanceStatus } from '@/lib/maintenance';

import { formatExpectedReturn } from '../format';

export type MaintenancePageProps = {
  status: MaintenanceStatus;
  onRecheck: () => void;
  /** Only the public entrance has a login screen; on the tailnet an
   *  administrator is recognised by their Tailscale identity instead. */
  showAdminLogin: boolean;
};

/**
 * What everyone but a platform administrator sees while the platform is
 * closed (#61), in place of whatever page they were on. Shown ahead of the
 * login redirect and the "Tailscale connection lost" state: during a hold
 * those would send people to fix something that is not broken.
 */
export function MaintenancePage({ status, onRecheck, showAdminLogin }: MaintenancePageProps) {
  const back = formatExpectedReturn(status.expected_return_at);
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <section
        role="status"
        aria-labelledby="maintenance-title"
        className="flex max-w-md flex-col items-center gap-4 rounded-lg border px-6 py-10 text-center"
      >
        <WrenchIcon className="size-6 text-muted-foreground" aria-hidden />
        <div className="space-y-2">
          <h1 id="maintenance-title" className="text-lg font-semibold">
            Closed for maintenance
          </h1>
          <p className="text-sm text-muted-foreground">
            {status.message ??
              'The platform is temporarily unavailable while administrators carry out maintenance.'}
          </p>
          {back ? (
            <p className="text-sm">
              Expected back: <time dateTime={status.expected_return_at ?? undefined}>{back}</time>
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">
            You were signed out. Sign in again once the platform reopens; API keys
            keep working afterwards without any change.
          </p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <Button variant="outline" size="sm" onClick={onRecheck}>
            Check again
          </Button>
          {showAdminLogin ? (
            <Link href="/login" className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
              Administrator sign-in
            </Link>
          ) : null}
        </div>
      </section>
    </div>
  );
}
