import { z } from 'zod';

/**
 * Parsed rather than cast, so a status the backend added and this build does
 * not know surfaces as a parse failure instead of a row that renders blank.
 * The enum mirrors `domain/entities/knowledge.py`.
 */
export const documentStatusSchema = z.enum([
  'uploaded',
  'extracting',
  'extracted',
  'indexing',
  'indexed',
  'error',
]);
export type DocumentStatus = z.infer<typeof documentStatusSchema>;

/** Which statuses a background task holds, matching TRANSIENT_DOCUMENT_STATES. */
export const TRANSIENT_STATUSES: readonly DocumentStatus[] = [
  'extracting',
  'indexing',
];

export const DOCUMENT_STATUS_HINT: Record<DocumentStatus, string> = {
  uploaded: 'Stored, waiting to be read.',
  extracting: 'The isolated parser is reading it.',
  extracted: 'Text is out; passages are being indexed.',
  indexing: 'Passages are being embedded and stored.',
  indexed: 'Searchable.',
  error: 'Ingestion failed. Delete and upload again to retry.',
};

export const collectionSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  document_count: z.number(),
  created_at: z.string().nullable(),
});
export const collectionListSchema = z.array(collectionSchema);
export type Collection = z.infer<typeof collectionSchema>;

export const documentSchema = z.object({
  id: z.string(),
  collection_id: z.string(),
  filename: z.string(),
  media_type: z.string(),
  size_bytes: z.number(),
  status: documentStatusSchema,
  chunk_count: z.number(),
  error: z.string().nullable(),
  uploaded_by: z.string(),
  uploaded_at: z.string().nullable(),
});
export type KnowledgeDocument = z.infer<typeof documentSchema>;

export const documentPageSchema = z.object({
  documents: z.array(documentSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type DocumentPage = z.infer<typeof documentPageSchema>;

export const passageSchema = z.object({
  document_id: z.string(),
  collection_id: z.string(),
  index: z.number(),
  /**
   * Untrusted document content. Rendered as plain text, never as markdown or
   * HTML: a passage is quoted from a file somebody uploaded (security.md 7.3).
   */
  text: z.string(),
  score: z.number(),
});
export const searchResponseSchema = z.object({
  passages: z.array(passageSchema),
});
export type Passage = z.infer<typeof passageSchema>;

export const createCollectionSchema = z.object({
  name: z.string().min(1, 'Required').max(128),
  description: z.string().max(1024).optional(),
});
export type CreateCollectionInput = z.input<typeof createCollectionSchema>;

/**
 * Mirrors `domain/services/upload_policy.py`. The server's copy is the one that
 * decides; this exists so a file it would refuse is refused before it is sent,
 * which for a 32 MiB upload is the difference between an instant message and a
 * long wait for a 413.
 */
export const MAX_UPLOAD_BYTES = 32 * 1024 * 1024;

export const ACCEPTED_MEDIA_TYPES: Record<string, string> = {
  'application/pdf': 'PDF',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
    'Word',
  'text/plain': 'Text',
  'text/markdown': 'Markdown',
};

/** For the file input's `accept`, which matches on extension in most browsers. */
export const ACCEPT_ATTRIBUTE = '.pdf,.docx,.txt,.md';

export function describeUploadRefusal(file: File): string | null {
  if (file.size === 0) return 'That file is empty.';
  if (file.size > MAX_UPLOAD_BYTES) {
    return `That file is ${formatBytes(file.size)}, over the ${formatBytes(
      MAX_UPLOAD_BYTES,
    )} limit.`;
  }
  // Browsers leave `type` empty for extensions they do not know, and the server
  // decides regardless, so an empty type is passed through rather than refused
  // here: guessing from the name is exactly what the backend refuses to do.
  if (file.type && !(file.type in ACCEPTED_MEDIA_TYPES)) {
    return 'That file type is not accepted. Upload a PDF, Word, text or markdown file.';
  }
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
