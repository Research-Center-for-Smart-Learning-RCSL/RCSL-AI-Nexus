import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { PromptTemplateTable } from '@/features/prompt-templates/components/prompt-template-table';

export const metadata: Metadata = { title: 'Prompt templates' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function PromptTemplatesPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Prompt templates</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Standing instructions to a model, saved under a name so they can be
          reused without being retyped. A template holds a name, a short
          description, and the instruction text itself — for example a reviewing
          style, a required output language, or a tone to keep to.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Applying one is a choice made per request: send its name as{' '}
          <code className="font-mono text-xs">prompt_template</code> from your
          own code. The chat screen in this application does not offer them, so
          a template affects API callers only. The text is placed at the front
          of the conversation, ahead
          of any instructions the caller sends, and those are kept rather than
          replaced. A name that does not exist is refused, so a request never
          quietly runs without the template it asked for.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          <strong>There is no variable substitution.</strong> A template is
          fixed text; what a caller chooses is which one, never what it says.
          That is deliberate — a template whose body could be filled in from a
          request would let the caller write the instructions the model treats
          as authoritative. Templates belong to your tenant and are not visible
          to any other.
        </p>
      </div>
      <PromptTemplateTable />
      <RelatedScreens
        items={[
          {
            href: '/chat',
            label: 'Chat',
            note: 'the same models, asked directly and signed in as yourself; templates are not applied there',
          },
          {
            href: '/api-docs',
            label: 'API reference',
            note: 'the request field to send a template name from your own code, alongside the other options a request accepts',
          },
        ]}
      />
    </div>
  );
}
