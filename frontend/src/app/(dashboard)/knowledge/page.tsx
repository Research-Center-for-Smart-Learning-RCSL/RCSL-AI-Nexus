import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { KnowledgeWorkspace } from '@/features/knowledge/components/knowledge-workspace';

export const metadata: Metadata = { title: 'Knowledge' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function KnowledgePage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Knowledge</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Documents a model can draw on when answering. Files are grouped into
          collections, and a question can be pointed at one collection or at
          everything. Accepted formats are PDF, DOCX, plain text and Markdown,
          up to 32 MB per file; other formats are refused rather than parsed,
          because every format accepted is a parser this deployment has to run.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          An upload is read by an isolated parser, split into passages and
          indexed. Only passages that match a question are placed alongside it —
          the model does not read the whole library, so a large collection does
          not slow answers down, but a document that never matches is never
          used. The <strong>Search</strong> tab runs retrieval on its own, which
          is how to check what a question would actually find before blaming an
          answer.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Retrieval is off unless a request asks for it. Everything here belongs
          to your tenant and is not visible to any other, and answers are drawn
          only from your tenant&apos;s collections.
        </p>
      </div>
      <KnowledgeWorkspace />
      <RelatedScreens
        items={[
          {
            href: '/chat',
            label: 'Chat',
            note: 'where these documents are actually used: enable retrieval on a conversation to have answers drawn from them',
          },
          {
            href: '/api-docs',
            label: 'API reference',
            note: 'the request fields that turn retrieval on and restrict it to one collection from your own code',
          },
        ]}
      />
    </div>
  );
}
