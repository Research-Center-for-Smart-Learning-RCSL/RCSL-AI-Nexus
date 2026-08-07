import type { Metadata } from 'next';

import { AgentSetup } from '@/features/gateway/components/agent-setup';

export const metadata: Metadata = { title: 'Connect an agent' };

export default function AgentSetupPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-heading text-lg font-semibold">Connect an agent</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Setting up a coding agent against this deployment, in order, with the
          settings that are wrong by default. The API page is the contract; this
          is the walkthrough. Every step was run end to end against this
          platform rather than copied from a client&apos;s documentation.
        </p>
      </div>
      <AgentSetup />
    </div>
  );
}
