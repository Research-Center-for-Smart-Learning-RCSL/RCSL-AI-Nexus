import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { AccountSettings } from '@/features/account/components/account-settings';

export const metadata: Metadata = { title: 'Account' };

export default function AccountPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Account"
        lead="The password and authenticator app belonging to the signed-in account."
      >
        <p>
          Changes made here affect no other account. Administrators change their
          own credentials by the same procedure; no account&apos;s password can
          be set on its behalf from this application.
        </p>
        <p>
          Both credentials are required only for signing in from outside the
          private network. Over the private network the account is identified by
          the network itself and neither is requested.
        </p>
        <p>
          Retain the recovery codes on a device other than the one holding the
          authenticator. They are the only remaining means of access if that
          device is lost.
        </p>
      </PageHeader>
      <AccountSettings />
    </div>
  );
}
