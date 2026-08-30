'use client';

/**
 * Step-by-step setup for a coding agent, as distinct from the API reference.
 *
 * `/api-docs` is the contract: what the wire looks like, what every field
 * means, what each error code implies. This is the other thing somebody needs —
 * the six commands in order, with the two settings that are wrong by default
 * and the failures that look like the platform is broken when they are not.
 *
 * It exists because the runbook in the repository is for whoever deploys this,
 * and the person connecting an agent is usually neither in that repository nor
 * able to read it. Everything here was walked end to end on 2026-08-07 against
 * this deployment rather than copied from a client's documentation, which is
 * the distinction that matters: the previous version of these instructions
 * recommended a Codex setting that had been removed six months earlier.
 *
 * That distinction cuts the other way too, and did on 2026-08-09. This page
 * called Codex in the ChatGPT desktop app impossible, which was not a finding
 * but an assumption filling the space where the CLI had been tested and the
 * app had not. An operator connected the CLI and the app followed it across on
 * its own, because both used the same Codex home and user `config.toml`.
 * **What is written here as a limit needs testing at least as much as what is
 * written here as a step.**
 *
 * And on 2026-08-17 the same line cut a third way: what is written here as
 * *working* goes stale too. "Works, and needs no second setup" was true of the
 * direction that had been tested and false of the machine in front of us,
 * where the app's own tool surface reached the CLI through that shared file and
 * made every request too large to send before a word of it was typed. One
 * sentence of good news had been carrying an untested claim about the
 * conditions under which it holds.
 *
 * On 2026-08-18 the replacement claim went the same way, one day old. "The app
 * makes this machine unconnectable" was generalised from the single machine
 * that had failed, while the operator's own — same app, same build — had been
 * connected and working throughout. What differs is the number of plugins the
 * app injects. Both versions of this text were absolute, and the true statement
 * is a quantity: hence the two machines below, and the missing figure named as
 * missing rather than rounded to a claim.
 */

import { useRef } from 'react';

import { ExportMarkdown } from '@/components/composed/export-markdown';
import { useAssistantSurface } from '@/features/assistant/context';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';
import { CodexConfigurationSection } from './agent-setup-codex';
import { PlatformShellSection } from './agent-setup-platform';
import { ProfilesSection } from './agent-setup-profiles';
import { OtherClientsSection } from './agent-setup-other-clients';
import { TroubleshootingSection } from './agent-setup-troubleshooting';

export function AgentSetup() {
  const { data, isLoading } = useGatewayInfo();
  // Exported from what is rendered rather than from a second copy of it, so the
  // capability and base URL below travel with the file. See lib/markdown-export.
  const content = useRef<HTMLDivElement>(null);
  // The screen the assistant's own instructions send people to, which until
  // 2026-08-09 registered nothing — so the drawer fell back to `other`, whose
  // guidance opens "The operator has no settings form open", on the one page
  // where that is most obviously untrue.
  useAssistantSurface({ surface: 'agent_setup' });
  const baseUrl = data?.base_url ?? 'https://<gateway>';
  const capabilities = data?.capabilities ?? [];
  // `code` is the capability an agent should use when one exists: it is the one
  // an administrator sets deliberation off for. Falling back to whatever is
  // routable keeps the page honest on a deployment that has not created it.
  const agentCapability = capabilities.includes('code')
    ? 'code'
    : (capabilities[0] ?? 'chat');

  return (
    <div className="space-y-8">
      <div className="flex justify-end" data-md-skip>
        <ExportMarkdown
          contentRef={content}
          title="Connect an agent"
          filename="connect-an-agent"
        />
      </div>
      <div ref={content} className="space-y-8">
        <CodexConfigurationSection baseUrl={baseUrl} agentCapability={agentCapability} />

      <PlatformShellSection agentCapability={agentCapability} />

      <ProfilesSection agentCapability={agentCapability} />

      <OtherClientsSection agentCapability={agentCapability} />

      <TroubleshootingSection />

      {isLoading ? null : capabilities.includes('code') ? null : (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          This deployment has no <code>code</code> capability. An agent operates
          against any routable capability, but <code>code</code> is the one an
          administrator sizes for agents: one model, no fallback, deliberation
          disabled. Request it before directing production work at this
          deployment.
        </p>
      )}
      </div>
    </div>
  );
}
