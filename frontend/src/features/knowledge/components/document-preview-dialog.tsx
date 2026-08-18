'use client';

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/composed/error-state';
import { useDocumentText } from '@/features/knowledge/hooks/use-knowledge';
import type { KnowledgeDocument } from '@/features/knowledge/schema';

export type DocumentPreviewDialogProps = {
  document: KnowledgeDocument | null;
  onOpenChange: (open: boolean) => void;
};

/**
 * What the parser made of a document — which is the question a preview answers
 * here, rather than "what does the file look like".
 *
 * **Rendered as plain text, never as markdown or markup.** A document is
 * attacker-supplied content and the whole reason parsing happens in an isolated
 * container; passing its text through a renderer on this page would undo that at
 * the last step. `whitespace-pre-wrap` keeps the parser's own line breaks, which
 * is exactly what an operator checking an extraction wants to see.
 */
export function DocumentPreviewDialog({
  document,
  onOpenChange,
}: DocumentPreviewDialogProps) {
  const { data, isLoading, error, refetch } = useDocumentText(
    document?.id ?? null,
  );

  return (
    <Dialog open={Boolean(document)} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          {/* The filename is an uploader-supplied string; the server sanitises
              it for display and this renders it as text, like the table does. */}
          <DialogTitle>{document?.filename ?? 'Document'}</DialogTitle>
          <DialogDescription>
            The text extracted from this document. This is what was chunked,
            embedded and indexed — not the original file.
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Loading the extracted text…
          </p>
        ) : error ? (
          <ErrorState
            title="Could not read the extracted text"
            error={error}
            onRetry={() => void refetch()}
          />
        ) : (
          <>
            <pre className="max-h-[50vh] overflow-auto overscroll-contain rounded-md border bg-muted/40 p-3 text-xs whitespace-pre-wrap break-words">
              {data?.text || 'The parser found no text in this document.'}
            </pre>
            {data?.truncated ? (
              <p className="text-xs text-muted-foreground">
                Truncated: this preview is bounded, not the stored text. What is
                indexed depends on the status — a document that says{' '}
                <em>indexed</em> has all of this searchable, while one still{' '}
                <em>extracted</em> has none of it yet and one in{' '}
                <em>error</em> may have stopped part way.
              </p>
            ) : null}
          </>
        )}

        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Close</DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
