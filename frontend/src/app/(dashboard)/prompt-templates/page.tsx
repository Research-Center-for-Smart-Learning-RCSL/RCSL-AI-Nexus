import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { PromptTemplateTable } from '@/features/prompt-templates/components/prompt-template-table';

export const metadata: Metadata = { title: 'Prompt templates' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function PromptTemplatesPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Prompt templates"
        lead="Standing instructions to a model, stored under a name so that they can be reused without being re-entered."
      >
        <p>
          A template holds a name, a short description and the instruction text
          itself: for example a review style, a required output language, or a
          register to maintain.
        </p>
        <p>
          A template is applied per request, by sending its name as{' '}
          <code className="font-mono text-xs">prompt_template</code> from
          external code. The chat screen in this application does not offer
          them, so a template affects API callers only. The text is placed at
          the front of the conversation, ahead of any instructions the caller
          sends, and those are retained rather than replaced. A name that does
          not exist is refused, so a request never proceeds without the template
          it specified.
        </p>
        <p>
          <strong>There is no variable substitution.</strong> A template is
          fixed text; the caller chooses which template applies, never what it
          says. A template whose body could be completed from a request would
          permit the caller to write the instructions the model treats as
          authoritative. Templates belong to a single tenant and are not visible
          to any other.
        </p>
      </PageHeader>
      <PromptTemplateTable />
      <RelatedScreens
        items={[
          {
            href: '/chat',
            label: 'Chat',
            note: 'the same models, asked directly under the signed-in identity; templates are not applied there',
          },
          {
            href: '/api-docs',
            label: 'API reference',
            note: 'the request field that carries a template name from external code, alongside the other options a request accepts',
          },
        ]}
      />
    </div>
  );
}
