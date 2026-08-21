import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { KnowledgeWorkspace } from '@/features/knowledge/components/knowledge-workspace';

export const metadata: Metadata = { title: 'Knowledge' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function KnowledgePage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Knowledge"
        lead="Documents from which a model may draw when answering, grouped into collections that a question can be directed at individually or in full."
      >
        <p>
          The accepted formats are PDF, DOCX, plain text and Markdown, up to
          32 MiB per file. Other formats are refused rather than parsed, since
          every format accepted is a parser this deployment must run.
        </p>
        <p>
          An upload is read by an isolated parser, divided into passages and
          indexed. Only passages matching a question are placed alongside it:
          the model does not read the whole collection, so a large collection
          does not delay answers, but a document that never matches is never
          used. The <strong>Search</strong> tab performs retrieval on its own,
          which is the means of establishing what a question retrieves before
          attributing a poor answer to the documents behind it.
        </p>
        <p>
          Retrieval is performed only where a request asks for it. All content
          here belongs to the tenant that uploaded it, is not visible to any
          other tenant, and answers are drawn only from the tenant&apos;s own
          collections.
        </p>
      </PageHeader>
      <KnowledgeWorkspace />
      <RelatedScreens
        items={[
          {
            href: '/chat',
            label: 'Chat',
            note: 'where these documents are used: enable retrieval on a conversation to have answers drawn from them',
          },
          {
            href: '/api-docs',
            label: 'API reference',
            note: 'the request fields that enable retrieval and restrict it to one collection from external code',
          },
        ]}
      />
    </div>
  );
}
