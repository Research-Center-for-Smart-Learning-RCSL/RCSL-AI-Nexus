'use client';

import Link from 'next/link';

/**
 * Shown to platform administrators on every screen while the platform is
 * closed, so nobody forgets it is (#61). They keep the management screens;
 * chat, the assistant and every model action answer `maintenance`.
 */
export function MaintenanceBanner() {
  return (
    <div
      role="status"
      className="border-b border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm"
    >
      <strong>Closed for maintenance.</strong> Only platform administrators can sign
      in, and no model serves anyone, administrators included.{' '}
      <Link href="/maintenance" className="underline underline-offset-2">
        Manage maintenance
      </Link>
    </div>
  );
}
