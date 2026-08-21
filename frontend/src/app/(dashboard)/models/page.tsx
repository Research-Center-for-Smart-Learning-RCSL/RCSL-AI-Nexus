import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { ModelTable } from '@/features/models/components/model-table';

export const metadata: Metadata = { title: 'Models' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function ModelsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Models"
        lead="The models registered with this deployment and the state of each one at present."
      >
        <p>
          Registering a model records its origin — a runtime reference such as{' '}
          <code className="font-mono text-xs">qwen2.5:7b</code> on a runtime and
          a node — together with the memory and context length to reserve for
          it. Registration fetches nothing: a model proceeds from registered to
          downloaded to loaded, and only a loaded model can serve a request.
        </p>
        <p>
          Assign each model an <strong>alias</strong>. Routing policies refer to
          the alias and never to the runtime reference, so replacing the model
          behind a name requires one edit here rather than an edit to every
          policy. The <strong>memory</strong> figure is what the load check
          budgets against, and <strong>context length</strong> is the window the
          runtime is sized for; prompt and reply share that window, so a value
          below what callers send truncates replies rather than refusing them.
        </p>
        <p>
          Two limits apply to this screen.{' '}
          <strong>
            The capabilities recorded against a model do not determine what it
            may serve
          </strong>{' '}
          — they are a label, and routing policies alone select models. Loading
          a model here does not make it reachable either; it becomes reachable
          when a policy names it.
        </p>
      </PageHeader>
      <ModelTable />
      <RelatedScreens
        items={[
          {
            href: '/nodes',
            label: 'Nodes',
            requires: 'node:read',
            note: 'a model is registered against a node and loads into that machine’s memory; the node’s total-memory figure is what the load check budgets against',
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
