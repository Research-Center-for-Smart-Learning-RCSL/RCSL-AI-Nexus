import { api } from '@/lib/api-client';
import {
  collectionListSchema,
  collectionSchema,
  documentPageSchema,
  documentSchema,
  documentTextSchema,
  resolveMediaType,
  searchResponseSchema,
  type Collection,
  type CreateCollectionInput,
  type DocumentPage,
  type DocumentText,
  type KnowledgeDocument,
  type Passage,
} from '@/features/knowledge/schema';

const BASE = '/knowledge';

export async function listCollections(): Promise<Collection[]> {
  return collectionListSchema.parse(await api.get<unknown>(`${BASE}/collections`));
}

export async function createCollection(
  input: CreateCollectionInput,
): Promise<Collection> {
  return collectionSchema.parse(
    await api.post<unknown>(`${BASE}/collections`, input),
  );
}

export async function deleteCollection(id: string): Promise<void> {
  await api.delete<void>(`${BASE}/collections/${id}`);
}

export async function listDocuments(params: {
  collectionId?: string;
  limit: number;
  offset: number;
}): Promise<DocumentPage> {
  return documentPageSchema.parse(
    await api.get<unknown>(`${BASE}/documents`, {
      query: {
        collection_id: params.collectionId,
        limit: params.limit,
        offset: params.offset,
      },
    }),
  );
}

/**
 * Multipart, which `api-client` passes through untouched: setting a
 * `Content-Type` by hand would drop the boundary the browser generates. The
 * CSRF header is still attached, because that is keyed on the method.
 */
export async function uploadDocument(
  collectionId: string,
  file: File,
): Promise<KnowledgeDocument> {
  const form = new FormData();
  form.append('collection_id', collectionId);

  // The multipart part carries the File's own `type`, which is empty for any
  // extension the OS does not have registered — `.md` on Windows, among others.
  // Re-wrapping is the only way to set the part's content type, and the
  // fallback covers the two text formats alone; see `resolveMediaType`.
  const mediaType = resolveMediaType(file);
  const part =
    file.type || !mediaType
      ? file
      : new File([file], file.name, { type: mediaType });
  form.append('file', part);

  return documentSchema.parse(
    await api.post<unknown>(`${BASE}/documents`, form),
  );
}

export async function deleteDocument(id: string): Promise<void> {
  await api.delete<void>(`${BASE}/documents/${id}`);
}

/**
 * The extracted text, for the preview. Never the uploaded file: serving that
 * back would hand the browser an attacker-supplied PDF to render, which is what
 * the isolated parser exists to keep out of this deployment.
 */
export async function readDocumentText(id: string): Promise<DocumentText> {
  return documentTextSchema.parse(
    await api.get<unknown>(`${BASE}/documents/${id}/text`),
  );
}

/**
 * Re-index from the text already extracted — no parser run, no re-upload.
 *
 * The 202 body is a job, and it is deliberately dropped: the table already
 * polls the document list while anything is mid-ingest, and the re-index moves
 * the row to `indexing`, so the existing poll reports it. A second progress
 * mechanism for the same work would be a second thing to keep in step.
 */
export async function reindexDocument(id: string): Promise<void> {
  await api.post<unknown>(`${BASE}/documents/${id}/reindex`, {});
}

/**
 * POST, not GET, and deliberately so: the query says what someone is looking
 * for in unpublished research, which is close enough to the content to keep out
 * of a URL. Query strings reach access logs and `Referer` headers, and the
 * proxy in front of the public entrance belongs to someone else.
 */
export async function searchKnowledge(params: {
  query: string;
  collectionId?: string;
  topK?: number;
}): Promise<Passage[]> {
  const body = await api.post<unknown>(`${BASE}/search`, {
    query: params.query,
    collection_id: params.collectionId ?? null,
    top_k: params.topK ?? 5,
  });
  return searchResponseSchema.parse(body).passages;
}
