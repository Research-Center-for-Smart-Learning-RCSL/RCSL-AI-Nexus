import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { UserTable } from '@/features/users/components/user-table';

export const metadata: Metadata = { title: 'Users' };

export default function UsersPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Users</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Who can sign in, and what each of them is allowed to do. Accounts are
          created by <strong>invitation only</strong> — there is no self
          sign-up, and an invitation that is never accepted grants nothing. A
          <strong> role</strong> is the whole of a person&apos;s permissions:
          roles are fixed sets rather than tick-boxes, so granting access means
          choosing the role whose job matches.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Someone who only ever works over the private network never needs a
          password — that entrance identifies them already. A password and an
          authenticator app are required only for signing in from outside it.
          Changing a role takes effect on the person&apos;s next request, and
          removing an account does not remove what it did: the audit log keeps
          that.
        </p>
      </div>
      <UserTable />
      <RelatedScreens
        items={[
          {
            href: '/tenants',
            label: 'Tenants',
            requires: 'tenant:read',
            note: 'every account belongs to exactly one tenant, which decides whose documents and usage it can reach',
          },
          {
            href: '/logs',
            label: 'Audit log',
            requires: 'logs:read',
            note: 'what each account has actually done, kept whether or not the account still exists',
          },
        ]}
      />
    </div>
  );
}
