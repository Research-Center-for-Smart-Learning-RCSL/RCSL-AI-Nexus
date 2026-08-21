'use client';

import { useRef, useState } from 'react';
import { UploadIcon } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/composed/data-table';
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
  describeUploadRefusal,
  type KnowledgeDocument,
} from '@/features/knowledge/schema';
import { useDocumentColumns } from './document-columns';

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

  const columns = useDocumentColumns({ reindex, setPreviewing, setDeleting });

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
        // For the same reason as the page size above: the rows the table can
        // see are one server page, so its own count would read "25 rows"
        // directly above this screen's "1-25 of 137".
        showRowCount={false}
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
