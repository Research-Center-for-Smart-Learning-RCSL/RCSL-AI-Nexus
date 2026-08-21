import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { PolicyTable } from '@/features/routing-policies/components/policy-table';

export const metadata: Metadata = { title: 'Routing policies' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function RoutingPoliciesPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Routing policies"
        lead="The rules that resolve a requested capability to the model that serves it."
      >
        <p>
          Callers request a <strong>capability</strong> — a name such as{' '}
          <code className="font-mono text-xs">chat</code> or{' '}
          <code className="font-mono text-xs">code</code> — and never a model. A
          policy is an ordered list of candidates, each a model alias with a
          priority and optional requirements. The highest-priority candidate
          whose requirements hold serves the request; where none holds, the
          caller receives{' '}
          <code className="font-mono text-xs">503 no_available_model</code>.
        </p>
        <p>
          Additional candidates act as a fallback. A second, smaller model keeps
          a capability answering while the first is not loaded, which suits
          interactive use. It suits automated callers less: a weaker model does
          not fail, it produces poorer output, and nothing in the reply
          identifies which model produced it. Requirements narrow the conditions
          under which a candidate is eligible — node online, model loaded, a
          minimum of free memory.
        </p>
        <p>
          <strong>Deliberation</strong> determines whether the model reasons
          before answering. It costs time on every request, and an agent incurs
          that cost again on every tool call, so capabilities used by coding
          agents are normally configured to answer directly. A capability
          becomes visible to callers as soon as a policy exists for it, and
          ceases to be available when the policy is deleted.
        </p>
      </PageHeader>
      <PolicyTable />
      <RelatedScreens
        items={[
          {
            href: '/models',
            label: 'Models',
            requires: 'model:read',
            note: 'candidates are model aliases from that screen, and a candidate whose model is not loaded is skipped',
          },
          {
            href: '/api-keys',
            label: 'API keys',
            note: 'a key is scoped to capability names, so a capability must have a policy here before a key can be issued for it',
          },
          {
            href: '/agent-setup',
            label: 'Connect an agent',
            note: 'coding agents incur the deliberation cost on every tool call, which is why they are given a capability configured to answer directly',
          },
        ]}
      />
    </div>
  );
}
