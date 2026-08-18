import { describe, expect, it } from 'vitest';

import {
  MAX_UPLOAD_BYTES,
  PREVIEWABLE_STATUSES,
  REINDEXABLE_STATUSES,
  TRANSIENT_STATUSES,
  collectionSchema,
  describeUploadRefusal,
  documentSchema,
  documentTextSchema,
  formatBytes,
  resolveMediaType,
  searchResponseSchema,
} from '@/features/knowledge/schema';

/**
 * The response schemas parse rather than cast, which is what turns a backend
 * change into a visible failure instead of a row rendering blank. The upload
 * policy is a mirror of the server's, so the cases here are the ones where a
 * mismatch would mean a 32 MiB round trip before the refusal.
 */

function file(name: string, type: string, size: number): File {
  const blob = new Blob([new Uint8Array(Math.min(size, 1024))], { type });
  const handle = new File([blob], name, { type });
  // jsdom builds `size` from the content, which is not what is under test here.
  Object.defineProperty(handle, 'size', { value: size });
  return handle;
}

describe('document schema', () => {
  it('rejects a status this build does not know', () => {
    const unknownStatus = {
      id: 'd1',
      collection_id: 'c1',
      filename: 'paper.pdf',
      media_type: 'application/pdf',
      size_bytes: 10,
      status: 'summarising',
      chunk_count: 0,
      error: null,
      uploaded_by: 'u1',
      uploaded_at: null,
    };
    expect(documentSchema.safeParse(unknownStatus).success).toBe(false);
  });

  it('accepts a document that failed, with its reason', () => {
    const parsed = documentSchema.parse({
      id: 'd1',
      collection_id: 'c1',
      filename: 'paper.pdf',
      media_type: 'application/pdf',
      size_bytes: 10,
      status: 'error',
      chunk_count: 0,
      error: 'DocumentParseError',
      uploaded_by: 'u1',
      uploaded_at: '2026-07-30T00:00:00Z',
    });
    expect(parsed.error).toBe('DocumentParseError');
  });
});

describe('collection schema', () => {
  it('requires the derived document count', () => {
    expect(
      collectionSchema.safeParse({
        id: 'c1',
        name: 'Papers',
        description: '',
        created_at: null,
      }).success,
    ).toBe(false);
  });
});

describe('search response schema', () => {
  it('parses passages with their score', () => {
    const parsed = searchResponseSchema.parse({
      passages: [
        {
          document_id: 'd1',
          collection_id: 'c1',
          index: 2,
          text: 'a passage',
          score: 0.87,
        },
      ],
    });
    expect(parsed.passages[0].index).toBe(2);
  });

  it('accepts an empty result', () => {
    expect(searchResponseSchema.parse({ passages: [] }).passages).toEqual([]);
  });
});

describe('upload policy, mirroring the server', () => {
  it('accepts the four types the parser handles', () => {
    expect(describeUploadRefusal(file('a.pdf', 'application/pdf', 10))).toBeNull();
    expect(describeUploadRefusal(file('a.txt', 'text/plain', 10))).toBeNull();
    expect(describeUploadRefusal(file('a.md', 'text/markdown', 10))).toBeNull();
    expect(
      describeUploadRefusal(
        file(
          'a.docx',
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          10,
        ),
      ),
    ).toBeNull();
  });

  it('refuses a type outside the allowlist', () => {
    expect(
      describeUploadRefusal(file('a.exe', 'application/x-msdownload', 10)),
    ).toMatch(/not accepted/);
  });

  it('refuses an empty file and one over the ceiling', () => {
    expect(describeUploadRefusal(file('a.pdf', 'application/pdf', 0))).toMatch(
      /empty/,
    );
    expect(
      describeUploadRefusal(file('a.pdf', 'application/pdf', MAX_UPLOAD_BYTES + 1)),
    ).toMatch(/limit/);
    expect(
      describeUploadRefusal(file('a.pdf', 'application/pdf', MAX_UPLOAD_BYTES)),
    ).toBeNull();
  });

  it('accepts a markdown file the browser could not identify', () => {
    // `.md` is unregistered on Windows and many Linux setups, so the browser
    // reports no type. Passing that through became `application/octet-stream`
    // server-side and was refused, for a file the picker explicitly invites.
    expect(describeUploadRefusal(file('notes.md', '', 10))).toBeNull();
    expect(resolveMediaType(file('notes.md', '', 10))).toBe('text/markdown');
    expect(resolveMediaType(file('notes.MD', '', 10))).toBe('text/markdown');
    expect(resolveMediaType(file('notes.txt', '', 10))).toBe('text/plain');
  });

  it('does not guess a type for the binary formats', () => {
    // Their parsers select on the declared type and the server checks it
    // against magic bytes, so a guess here could steer bytes at the wrong
    // format reader. Only the two text formats, whose parser is a decode, get
    // an extension fallback.
    expect(resolveMediaType(file('paper.pdf', '', 10))).toBe('');
    expect(describeUploadRefusal(file('paper.pdf', '', 10))).toMatch(
      /could not identify/,
    );
  });

  it('keeps a type the browser did supply', () => {
    expect(resolveMediaType(file('a.md', 'text/markdown', 10))).toBe('text/markdown');
  });
});

describe('formatBytes', () => {
  // Binary divisors, so the unit says so: the limit these messages quote is
  // 33,554,432 bytes, which is 32 MiB and 33.6 MB. Labelling it "32 MB" made
  // the refusal disagree with the ceiling it was refusing against.
  it('reads at the scale a person thinks in', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2 KiB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MiB');
  });

  it('names the upload ceiling in the unit it is enforced in', () => {
    expect(formatBytes(MAX_UPLOAD_BYTES)).toBe('32.0 MiB');
  });
});

describe('the preview and re-index gates', () => {
  it('parses the preview body, carrying the server\'s truncation flag', () => {
    const parsed = documentTextSchema.parse({
      document_id: 'd1',
      text: 'extracted',
      truncated: false,
    });
    expect(parsed.truncated).toBe(false);

    // Inferring truncation from the length here would need a copy of the
    // server's bound, which would disagree the first time either changed.
    expect(() =>
      documentTextSchema.parse({ document_id: 'd1', text: 'x' }),
    ).toThrow();
  });

  it('never offers re-index or preview while a task holds the row', () => {
    // Both are refused server-side for a transient document; the point of
    // checking here is that the button is not offered in the first place.
    for (const status of TRANSIENT_STATUSES) {
      expect(REINDEXABLE_STATUSES).not.toContain(status);
      expect(PREVIEWABLE_STATUSES).not.toContain(status);
    }
  });

  it('offers both on a failed document, which is the case they exist for', () => {
    // A post-extraction failure is exactly what re-indexing fixes without a
    // re-upload, and the extracted text is there to preview.
    expect(REINDEXABLE_STATUSES).toContain('error');
    expect(PREVIEWABLE_STATUSES).toContain('error');
  });

  it('offers neither before the parser has run', () => {
    expect(REINDEXABLE_STATUSES).not.toContain('uploaded');
    expect(PREVIEWABLE_STATUSES).not.toContain('uploaded');
  });
});
