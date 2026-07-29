import { describe, expect, it } from 'vitest';

import {
  MAX_UPLOAD_BYTES,
  collectionSchema,
  describeUploadRefusal,
  documentSchema,
  formatBytes,
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

  it('passes an unknown-to-the-browser type through to the server', () => {
    // Browsers leave `type` empty for extensions they do not recognise, and
    // guessing from the name is exactly what the backend refuses to do. Letting
    // it through means the server's allowlist decides, not the browser's guess.
    expect(describeUploadRefusal(file('a.md', '', 10))).toBeNull();
  });
});

describe('formatBytes', () => {
  it('reads at the scale a person thinks in', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });
});
