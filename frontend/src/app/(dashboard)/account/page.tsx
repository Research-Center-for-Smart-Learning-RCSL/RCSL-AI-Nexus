import type { Metadata } from 'next';

import { AccountSettings } from '@/features/account/components/account-settings';

export const metadata: Metadata = { title: 'Account' };

/**
 * The destination the shell header has linked to all along. Until this existed
 * the Account button was a 404 on every screen it appeared on, which was every
 * screen served from the public entrance.
 */
export default function AccountPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Account</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Your own password and authenticator. Nothing here affects anyone
          else&apos;s account, and administrators change these the same way you
          do.
        </p>
      </div>
      <AccountSettings />
    </div>
  );
}
