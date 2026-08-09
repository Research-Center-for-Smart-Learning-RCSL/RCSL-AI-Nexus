import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { ModelTable } from '@/features/models/components/model-table';

export const metadata: Metadata = { title: 'Models' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function ModelsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Models</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          The models this deployment knows about, and what each one is doing
          right now. Registering one records where it comes from — a runtime
          reference such as <code className="font-mono text-xs">qwen2.5:7b</code>{' '}
          on a runtime and a node — together with the memory and context length
          to reserve for it. Registering does not fetch anything: a model moves
          from registered to downloaded to loaded, and only a loaded model can
          serve a request.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Give each model an <strong>alias</strong>. Routing policies refer to
          the alias, never to the runtime reference, so replacing the model
          behind a name is one edit here rather than an edit to every policy.
          The <strong>memory</strong> figure is what the load check budgets
          against, and <strong>context length</strong> is the window the runtime
          is sized for — prompt and reply share it, so a value below what
          callers actually send truncates replies rather than refusing them.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Two things this screen does not do.{' '}
          <strong>
            The capabilities recorded against a model do not decide what it may
            serve
          </strong>{' '}
          — they are a label, and routing policies alone select models. And
          loading a model here does not make it reachable: it becomes reachable
          when a policy names it.
        </p>
      </div>
      <ModelTable />
      <RelatedScreens
        items={[
          {
            href: '/nodes',
            label: 'Nodes',
            requires: 'node:read',
            note: 'a model is registered against a node and loads into that machine\u2019s memory; the node\u2019s total-memory figure is what the load check budgets against',
          },
          {
            href: '/routing-policies',
            label: 'Routing policies',
            requires: 'routing:read',
            note: 'a loaded model serves nothing until a policy names its alias as a candidate',
          },
        ]}
      />
    </div>
  );
}
