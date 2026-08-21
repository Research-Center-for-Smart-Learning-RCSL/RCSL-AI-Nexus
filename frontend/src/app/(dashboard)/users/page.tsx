import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { UserTable } from '@/features/users/components/user-table';

export const metadata: Metadata = { title: 'Users' };

export default function UsersPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Users"
        lead="The accounts that may sign in, and what each of them is permitted to do."
      >
        <p>
          Accounts are created by <strong>invitation only</strong>. There is no
          self-registration, and an invitation that is never accepted grants
          nothing. A <strong>role</strong> constitutes the whole of an
          account&apos;s permissions: roles are fixed sets rather than
          individually selectable permissions, so granting access means
          selecting the role whose remit matches.
        </p>
        <p>
          An account used only over the private network requires no password,
          since that entrance identifies it already. A password and an
          authenticator app are required only for signing in from outside it.
        </p>
        <p>
          A change of role takes effect on the account&apos;s next request.
          Removing an account does not remove what it did: the audit log
          retains that record.
        </p>
      </PageHeader>
      <UserTable />
      <RelatedScreens
        items={[
          {
            href: '/tenants',
            label: 'Tenants',
            requires: 'tenant:read',
            note: 'every account belongs to exactly one tenant, which determines whose documents and usage it can reach',
          },
          {
            href: '/logs',
            label: 'Audit log',
            requires: 'logs:read',
            note: 'what each account has done, retained whether or not the account still exists',
          },
        ]}
      />
    </div>
  );
}
