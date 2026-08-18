'use client';

import { useMemo, useRef, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { UploadIcon } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/composed/data-table';
import { StatusBadge } from '@/components/composed/status-badge';
import { ConfirmDialog } from '@/components/composed/confirm-dialog';
import {
  useDeleteDocument,
  useDocuments,
  useReindexDocument,
  useUploadDocument,
} from '@/features/knowledge/hooks/use-knowledge';
import { DocumentPreviewDialog } from '@/features/knowledge/components/document-preview-dialog';
import {
  ACCEPT_ATTRIBUTE,
  DOCUMENT_STATUS_HINT,
  PREVIEWABLE_STATUSES,
  REINDEXABLE_STATUSES,
  TRANSIENT_STATUSES,
  describeUploadRefusal,
  formatBytes,
  type KnowledgeDocument,
} from '@/features/knowledge/schema';

const PAGE_SIZE = 25;

export type DocumentTableProps = {
  collectionId: string | undefined;
};

export function DocumentTable({ collectionId }: DocumentTableProps) {
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error, refetch } = useDocuments(
    collectionId,
    offset,
    PAGE_SIZE,
  );
  const remove = useDeleteDocument();
  const upload = useUploadDocument();
  const reindex = useReindexDocument();
  const fileInput = useRef<HTMLInputElement>(null);
  const [deleting, setDeleting] = useState<KnowledgeDocument | null>(null);
  const [previewing, setPreviewing] = useState<KnowledgeDocument | null>(null);

  const columns = useMemo<ColumnDef<KnowledgeDocument>[]>(
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
    [reindex],
  );

  const total = data?.total ?? 0;

  async function onFileChosen(file: File | undefined) {
    if (!file) return;
    if (!collectionId) {
      toast.error('Choose a collection before uploading.');
      return;
    }
    // Checked before sending, so a file the server would refuse anyway does not
    // travel first. The server's copy of this policy is the one that decides.
    const refusal = describeUploadRefusal(file);
    if (refusal) {
      toast.error(refusal);
      return;
    }
    await upload.mutateAsync({ collectionId, file });
  }

  return (
    <>
      <input
        ref={fileInput}
        type="file"
        accept={ACCEPT_ATTRIBUTE}
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          // Cleared so choosing the same file twice fires a change event again,
          // which matters when the first attempt failed.
          event.target.value = '';
          void onFileChosen(file);
        }}
      />

      <DataTable
        columns={columns}
        data={data?.documents}
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        // Matches the server page exactly, so the table's own pager never
        // engages. It defaults to 20, which split each 25-row page into a
        // "Page 1 of 2" sitting directly above a server pager reading
        // "1-25 of N" — two sets of Previous/Next, three clicks apart in
        // meaning, on the same screen.
        pageSize={PAGE_SIZE}
        searchPlaceholder="Filter the documents below"
        emptyTitle="No documents"
        emptyDescription={
          collectionId
            ? 'Upload a PDF, Word, text or markdown file to index it.'
            : 'Choose a collection, then upload a document into it.'
        }
        getRowId={(row) => row.id}
        toolbar={
          <Button
            size="sm"
            disabled={!collectionId || upload.isPending}
            onClick={() => fileInput.current?.click()}
          >
            <UploadIcon />
            {upload.isPending ? 'Uploading…' : 'Upload'}
          </Button>
        }
      />

      {/* Server-paged, like the audit log: the table only grows, and an
          unbounded read is a memory lever on both sides. */}
      {total > PAGE_SIZE ? (
        <div className="flex items-center justify-between pt-2 text-sm text-muted-foreground">
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="xs"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="xs"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}

      <DocumentPreviewDialog
        document={previewing}
        onOpenChange={(open) => {
          if (!open) setPreviewing(null);
        }}
      />

      <ConfirmDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={`Delete ${deleting?.filename ?? 'this document'}?`}
        description="The uploaded file and its indexed passages are removed with it. This cannot be undone."
        confirmLabel="Delete"
        destructive
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.id);
        }}
      />
    </>
  );
}
