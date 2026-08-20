'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';

import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/composed/status-badge';
import { useReindexDocument } from '@/features/knowledge/hooks/use-knowledge';
import { DOCUMENT_STATUS_HINT, PREVIEWABLE_STATUSES, REINDEXABLE_STATUSES, TRANSIENT_STATUSES, formatBytes, type KnowledgeDocument } from '@/features/knowledge/schema';

type Params = {
  reindex: ReturnType<typeof useReindexDocument>;
  setPreviewing: (document: KnowledgeDocument) => void;
  setDeleting: (document: KnowledgeDocument) => void;
};

export function useDocumentColumns(params: Params): ColumnDef<KnowledgeDocument>[] {
  const { reindex, setPreviewing, setDeleting } = params;
  return useMemo<ColumnDef<KnowledgeDocument>[]>(
    () => [
      {
        id: 'filename',
        accessorKey: 'filename',
        header: 'File',
        cell: ({ row }) => (
          // Plain text. The filename came from an upload, and while the server
          // sanitises it for display this never renders it as markup either.
          <span className="font-medium">{row.original.filename}</span>
        ),
      },
      {
        id: 'size',
        accessorFn: (row) => row.size_bytes,
        header: 'Size',
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatBytes(row.original.size_bytes)}
          </span>
        ),
      },
      {
        id: 'passages',
        accessorFn: (row) => row.chunk_count,
        header: 'Passages',
        cell: ({ row }) =>
          row.original.status === 'indexed' ? (
            row.original.chunk_count
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        id: 'status',
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => {
          const document = row.original;
  return (
            <div className="space-y-0.5">
              <StatusBadge status={document.status} />
              <p className="text-xs text-muted-foreground">
                {/* The failure class, never the parser's own message: that can
                    quote the document. See ingest_document.py. */}
                {document.status === 'error' && document.error
                  ? `${DOCUMENT_STATUS_HINT.error} (${document.error})`
                  : DOCUMENT_STATUS_HINT[document.status]}
              </p>
            </div>
          );
        },
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        enableHiding: false,
        cell: ({ row }) => {
          const document = row.original;
          const busy = TRANSIENT_STATUSES.includes(document.status);
          return (
            <div className="flex justify-end gap-1">
              {PREVIEWABLE_STATUSES.includes(document.status) && (
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => setPreviewing(document)}
                >
                  Preview
                </Button>
              )}
              {/* Re-index starts from the text already extracted, so it costs
                  no parser run and no re-upload. Offered on `error` too: that
                  is the case it exists for. The one shape it cannot fix — a
                  failure during extraction, where no text was ever stored —
                  says so only in the job body, which nothing here reads, so the
                  row just returns to `error` and the status hint is what has to
                  explain it. */}
              {REINDEXABLE_STATUSES.includes(document.status) && (
                <Button
                  variant="outline"
                  size="xs"
                  disabled={busy || reindex.isPending}
                  onClick={() => reindex.mutate(document.id)}
                >
                  Re-index
                </Button>
              )}
              <Button
                variant="ghost"
                size="xs"
                className="text-destructive"
                // Refused server-side while a background task still holds the
                // row; disabling here only saves the round trip.
                disabled={busy}
                onClick={() => setDeleting(document)}
              >
                Delete
              </Button>
            </div>
          );
        },
      },
    ],
    [reindex, setPreviewing, setDeleting],
  );
}
