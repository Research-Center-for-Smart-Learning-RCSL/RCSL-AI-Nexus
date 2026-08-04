'use client';

import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { PlusIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/composed/data-table';
import { useSession } from '@/lib/session';
import { useTenants } from '@/features/tenants/hooks/use-tenants';
import { CreateTenantDialog } from '@/features/tenants/components/create-tenant-dialog';
import type { Tenant } from '@/features/tenants/schema';

export function TenantTable() {
  const { can } = useSession();
  const mayWrite = can('tenant:write');
  const { data, isLoading, error, refetch } = useTenants();
  const [createOpen, setCreateOpen] = useState(false);

  const columns = useMemo<ColumnDef<Tenant>[]>(
    () => [
      {
        id: 'name',
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
      },
      {
        id: 'id',
        accessorKey: 'id',
        header: 'ID',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">{row.original.id}</span>
        ),
      },
      {
        id: 'created_at',
        accessorKey: 'created_at',
        header: 'Created',
        cell: ({ row }) =>
          row.original.created_at
            ? new Date(row.original.created_at).toLocaleDateString()
            : '',
      },
    ],
    [],
  );

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        searchPlaceholder="Search tenants"
        emptyTitle="No tenants"
        emptyDescription="Every account belongs to a tenant. Create one to isolate a group's users and keys."
        getRowId={(row) => row.id}
        toolbar={
          mayWrite ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <PlusIcon />
              Create tenant
            </Button>
          ) : null
        }
      />

      <CreateTenantDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}
