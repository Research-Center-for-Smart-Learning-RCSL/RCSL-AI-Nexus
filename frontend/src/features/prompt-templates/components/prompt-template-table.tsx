'use client';

import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { PlusIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/composed/data-table';
import { ConfirmDialog } from '@/components/composed/confirm-dialog';
import { useSession } from '@/lib/session';
import {
  useDeletePromptTemplate,
  usePromptTemplates,
} from '@/features/prompt-templates/hooks/use-prompt-templates';
import { PromptTemplateDialog } from '@/features/prompt-templates/components/prompt-template-dialog';
import type { PromptTemplate } from '@/features/prompt-templates/schema';

export function PromptTemplateTable() {
  // `prompt:write` rather than a role: `curator` and `tenant_admin` both hold
  // it, and `auditor` and `operator` may read this screen without being offered
  // actions the server will refuse.
  const { can } = useSession();
  const mayWrite = can('prompt:write');
  const { data, isLoading, error, refetch } = usePromptTemplates();
  const remove = useDeletePromptTemplate();

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<PromptTemplate | null>(null);
  const [deleting, setDeleting] = useState<PromptTemplate | null>(null);

  const columns = useMemo<ColumnDef<PromptTemplate>[]>(
    () => [
      {
        id: 'name',
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => (
          <div>
            {/* Monospace, because this is the string a caller types into
                `"prompt_template": "..."` rather than a label. */}
            <div className="font-mono text-sm font-medium">{row.original.name}</div>
            {row.original.description ? (
              <div className="text-xs text-muted-foreground">{row.original.description}</div>
            ) : null}
          </div>
        ),
      },
      {
        id: 'system_prompt',
        header: 'System prompt',
        enableSorting: false,
        cell: ({ row }) => (
          <p className="max-w-prose truncate text-xs text-muted-foreground">
            {row.original.system_prompt}
          </p>
        ),
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        enableHiding: false,
        cell: ({ row }) => {
          if (!mayWrite) return null;
          return (
            <div className="flex justify-end gap-1">
              <Button variant="ghost" size="xs" onClick={() => setEditing(row.original)}>
                Edit
              </Button>
              <Button
                variant="ghost"
                size="xs"
                className="text-destructive"
                onClick={() => setDeleting(row.original)}
              >
                Delete
              </Button>
            </div>
          );
        },
      },
    ],
    [mayWrite],
  );

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        searchPlaceholder="Search templates"
        emptyTitle="No prompt templates yet"
        emptyDescription="A template is a system prompt a caller selects by name. There is no variable substitution: what a caller chooses is which one, not what it says."
        getRowId={(row) => row.id}
        toolbar={
          mayWrite ? (
            <Button size="sm" onClick={() => setCreating(true)}>
              <PlusIcon />
              New template
            </Button>
          ) : null
        }
      />

      {/* Mounted only while one is selected, so the form defaults and the
          `useUpdatePromptTemplate(id)` inside both belong to that row. */}
      {creating ? (
        <PromptTemplateDialog template={null} onClose={() => setCreating(false)} />
      ) : null}
      {editing ? (
        <PromptTemplateDialog template={editing} onClose={() => setEditing(null)} />
      ) : null}

      <ConfirmDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={`Delete ${deleting?.name ?? 'this template'}?`}
        description="Conversations already sent are unaffected — the template was copied into those requests. The next request naming it is refused rather than served without it."
        confirmLabel="Delete"
        destructive
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.id);
        }}
      />
    </>
  );
}
