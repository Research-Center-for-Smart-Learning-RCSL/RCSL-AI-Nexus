import type { Metadata } from 'next';

import { UserTable } from '@/features/users/components/user-table';

export const metadata: Metadata = { title: 'Users' };

export default function UsersPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Users</h1>
        <p className="text-sm text-muted-foreground">
          Invitation only. Someone who only ever works over the tailnet never
          needs a password.
        </p>
      </div>
      <UserTable />
    </div>
  );
}
