import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { AgentSetup } from '@/features/gateway/components/agent-setup';

export const metadata: Metadata = { title: 'Connect an agent' };

export default function AgentSetupPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Connect an agent"
        lead="The procedure for configuring a coding agent against this deployment, in order, including the settings whose defaults are unsuitable."
      >
        <p>
          The API reference states the contract; this page states the procedure.
          Each step has been executed against this deployment rather than
          transcribed from a client&apos;s own documentation.
        </p>
      </PageHeader>
      <AgentSetup />
    </div>
  );
}
