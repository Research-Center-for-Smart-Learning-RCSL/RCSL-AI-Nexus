import type { Metadata } from 'next';

import { PromptTemplateTable } from '@/features/prompt-templates/components/prompt-template-table';

export const metadata: Metadata = { title: 'Prompt templates' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function PromptTemplatesPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Prompt templates</h1>
        <p className="text-sm text-muted-foreground">
          A named system prompt a caller selects with{' '}
          <code className="font-mono text-xs">&quot;prompt_template&quot;</code>.
          It is placed at the front of the conversation, ahead of any system
          message the caller sends, which is kept. There is no variable
          substitution — what a caller chooses is which template, not what it
          says.
        </p>
      </div>
      <PromptTemplateTable />
    </div>
  );
}
