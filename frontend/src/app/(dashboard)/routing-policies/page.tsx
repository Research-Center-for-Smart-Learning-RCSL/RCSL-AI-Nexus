import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { PolicyTable } from '@/features/routing-policies/components/policy-table';

export const metadata: Metadata = { title: 'Routing policies' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function RoutingPoliciesPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Routing policies</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Callers ask for a <strong>capability</strong> — a name such as{' '}
          <code className="font-mono text-xs">chat</code> or{' '}
          <code className="font-mono text-xs">code</code> — never for a model. A
          policy is what turns that name into a model: an ordered list of
          candidates, each a model alias with a priority and optional
          requirements. The highest-priority candidate whose requirements hold
          serves the request; if none holds, the caller receives{' '}
          <code className="font-mono text-xs">503 no_available_model</code>.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Extra candidates are a fallback. A second, smaller model keeps a
          capability answering when the first is not loaded, which suits people
          asking questions; it suits automated callers less, because a weaker
          model does not fail, it produces worse output, and nothing in the
          reply says which model wrote it. Requirements narrow when a candidate
          is eligible — node online, model loaded, a minimum of free memory.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          <strong>Deliberation</strong> decides whether the model reasons before
          answering. It costs time on every request, and an agent pays it again
          on every tool call, so capabilities used by coding agents are normally
          set to answer directly. A capability appears to callers as soon as a
          policy exists for it, and disappears when the policy is deleted.
        </p>
      </div>
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
            note: 'a key is scoped to capability names, so a capability has to have a policy here before a key can be issued for it',
          },
          {
            href: '/agent-setup',
            label: 'Connect an agent',
            note: 'coding agents pay the deliberation cost on every tool call, which is why they are given a capability set to answer directly',
          },
        ]}
      />
    </div>
  );
}
