'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  createCollection,
  deleteCollection,
  deleteDocument,
  listCollections,
  listDocuments,
  readDocumentText,
  reindexDocument,
  searchKnowledge,
  uploadDocument,
} from '@/features/knowledge/api';
import {
  TRANSIENT_STATUSES,
  type CreateCollectionInput,
  type DocumentPage,
} from '@/features/knowledge/schema';
import { describeError } from '@/components/composed/error-state';

export const knowledgeKeys = {
  all: ['knowledge'] as const,
  collections: () => [...knowledgeKeys.all, 'collections'] as const,
  documents: (collectionId: string | undefined, offset: number) =>
    [...knowledgeKeys.all, 'documents', collectionId ?? 'all', offset] as const,
  text: (documentId: string) =>
    [...knowledgeKeys.all, 'text', documentId] as const,
};

export function useCollections() {
  return useQuery({
    queryKey: knowledgeKeys.collections(),
    queryFn: listCollections,
  });
}

/**
 * Polled only while something is mid-ingest.
 *
 * Ingestion is a background task whose progress is not pushed, so the table has
 * to ask. Polling unconditionally would keep an idle knowledge page querying
 * forever; polling never would leave a document stuck on "extracting" until a
 * manual reload. The predicate form asks only while there is an answer to wait
 * for, which is also how the operator knows the work is still running.
 */
export function useDocuments(collectionId: string | undefined, offset: number, limit: number) {
  return useQuery({
    queryKey: knowledgeKeys.documents(collectionId, offset),
    queryFn: () => listDocuments({ collectionId, limit, offset }),
    refetchInterval: (query) => {
      const page = query.state.data as DocumentPage | undefined;
      const busy = page?.documents.some((d) =>
        TRANSIENT_STATUSES.includes(d.status),
      );
      return busy ? 2_000 : false;
    },
  });
}

function useInvalidateKnowledge() {
  const queryClient = useQueryClient();
  // The whole prefix: a document changes the collection's count as well as the
  // document list, and the two are separate queries.
  return () => queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
}

export function useCreateCollection() {
  const invalidate = useInvalidateKnowledge();
  return useMutation({
    mutationFn: (input: CreateCollectionInput) => createCollection(input),
    onSuccess: async (collection) => {
      await invalidate();
      toast.success(`Created ${collection.name}.`);
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useDeleteCollection() {
  const invalidate = useInvalidateKnowledge();
  return useMutation({
    mutationFn: (id: string) => deleteCollection(id),
    onSuccess: async () => {
      await invalidate();
      toast.success('Collection deleted, with its documents.');
    },
    // Refused while a document is mid-ingest, with the server saying so.
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useUploadDocument() {
  const invalidate = useInvalidateKnowledge();
  return useMutation({
    mutationFn: ({ collectionId, file }: { collectionId: string; file: File }) =>
      uploadDocument(collectionId, file),
    onSuccess: async (document) => {
      await invalidate();
      // 202: the row exists, the document has not been read yet. Saying
      // "uploaded" rather than "indexed" is the honest version, and the table's
      // status column carries the rest.
      toast.success(`Uploaded ${document.filename}. Reading it now.`);
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

export function useDeleteDocument() {
  const invalidate = useInvalidateKnowledge();
  return useMutation({
    mutationFn: (id: string) => deleteDocument(id),
    onSuccess: async () => {
      await invalidate();
      toast.success('Document deleted, with its passages.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

/**
 * The preview, fetched only while the dialog is open.
 *
 * `enabled` on the id rather than a separate open flag: the dialog is rendered
 * from the same state that holds the document, so a null id already means
 * closed, and the text is not fetched for every row of the table.
 */
export function useDocumentText(documentId: string | null) {
  return useQuery({
    queryKey: knowledgeKeys.text(documentId ?? 'none'),
    queryFn: () => readDocumentText(documentId as string),
    enabled: documentId !== null,
    // The extracted text does not change unless the document is re-uploaded,
    // which replaces the row, so nothing is gained by re-asking on remount.
    staleTime: Infinity,
  });
}

export function useReindexDocument() {
  const invalidate = useInvalidateKnowledge();
  return useMutation({
    mutationFn: (id: string) => reindexDocument(id),
    onSuccess: async () => {
      await invalidate();
      // 202, like the upload: accepted, not finished. The row moves to
      // `indexing` and the table's poll reports where it lands. The one failure
      // re-indexing cannot fix — a document with no text stored — lands back on
      // `error` with its explanation in the job body this deliberately drops.
      toast.success('Re-indexing from the stored text.');
    },
    onError: (error) => toast.error(describeError(error)),
  });
}

/**
 * A mutation rather than a query, because searching is an action the operator
 * takes: caching it by query string would re-run stale searches on remount and
 * show results for a question nobody just asked.
 */
export function useSearchKnowledge() {
  return useMutation({
    mutationFn: (params: { query: string; collectionId?: string }) =>
      searchKnowledge(params),
    onError: (error) => toast.error(describeError(error)),
  });
}
