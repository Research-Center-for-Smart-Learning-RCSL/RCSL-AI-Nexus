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
 */

import { CodeBlock } from '@/components/composed/code-block';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <h3 className="font-heading text-sm font-semibold">
        <span className="mr-2 inline-flex size-5 items-center justify-center rounded-full bg-muted text-xs">
          {n}
        </span>
        {title}
      </h3>
      <div className="space-y-2 pl-7 text-sm text-muted-foreground">
        {children}
      </div>
    </div>
  );
}

export function AgentSetup() {
  const { data, isLoading } = useGatewayInfo();
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
      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Codex — verified against this deployment
        </h2>
        <p className="text-sm text-muted-foreground">
          Six steps. Two of them carry a setting that is wrong by default and
          fails in a way that looks like something else.
        </p>

        <div className="space-y-5 pt-1">
          <Step n={1} title="Issue a key for one capability">
            <p>
              On <strong>API keys</strong>, issue a key scoped to{' '}
              <code>{agentCapability}</code> and nothing else. Two defaults are
              wrong for an agent and both fail mid-task:
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <strong>Requests per minute.</strong> An agent makes one request
                per step and a task is tens of steps. A limit sized for a person
                typing produces <code>429</code> half way through.
              </li>
              <li>
                <strong>Daily token quota.</strong> An agent replays the whole
                conversation every turn, and prompt tokens count. Consumption
                grows roughly with the square of a task&apos;s length, not
                linearly. Size it generously.
              </li>
            </ul>
            <p>
              Leave <strong>allowed CIDRs</strong> empty unless that machine has
              a fixed public address. A dynamic one changes on reconnect and the
              resulting <code>401</code> does not say why — deliberately, since
              naming the rule that refused you is free reconnaissance.
            </p>
          </Step>

          <Step n={2} title="Install the client">
            <CodeBlock code={'npm install -g @openai/codex'} label="Copy" />
            <p>
              Needs Node. On Windows PowerShell may refuse to run{' '}
              <code>npm</code> until you allow local scripts once:{' '}
              <code>Set-ExecutionPolicy -Scope CurrentUser RemoteSigned</code>.
              That is per-user, needs no administrator, and is the value
              Microsoft recommends for a workstation.
            </p>
          </Step>

          <Step n={3} title="Write the configuration">
            <p>
              <code>~/.codex/config.toml</code>, or{' '}
              <code>%USERPROFILE%\.codex\config.toml</code> on Windows:
            </p>
            <CodeBlock
              code={`model = "${agentCapability}"
model_provider = "rcsl"

[model_providers.rcsl]
name = "RCSL AI Nexus"
base_url = "${baseUrl}/v1"
env_key = "RCSL_API_KEY"
wire_api = "responses"`}
              label="Copy config.toml"
            />
            <p>
              <strong>
                <code>wire_api</code> must be <code>responses</code>.
              </strong>{' '}
              Codex removed Chat Completions support in February 2026 and
              refuses to start on <code>wire_api = &quot;chat&quot;</code>. Any
              guide still showing <code>&quot;chat&quot;</code> predates that,
              including an earlier version of this page.
            </p>
            <p>
              <strong>
                <code>model</code> takes a capability, not a model name.
              </strong>{' '}
              <code>{agentCapability}</code>, never the name of the model
              serving it. This is the platform&apos;s one real divergence from
              other providers.
            </p>
          </Step>

          <Step n={4} title="Export the key">
            <CodeBlock
              code={'export RCSL_API_KEY=nx_live_...'}
              label="Copy (macOS, Linux)"
            />
            <CodeBlock
              code={'setx RCSL_API_KEY "nx_live_..."'}
              label="Copy (Windows)"
            />
            <p>
              On Windows <code>setx</code> writes the variable for future
              processes only. <strong>Close the terminal and open a new one</strong>{' '}
              or the client will not see it.
            </p>
          </Step>

          <Step n={5} title="Check the platform half before involving the agent">
            <CodeBlock
              code={`curl ${baseUrl}/v1/models -H "Authorization: Bearer $RCSL_API_KEY"`}
              label="Copy the check"
            />
            <p>
              A list naming your capability means the whole path works: network,
              perimeter, key, routing. A failure here is a deployment problem; a
              failure only inside the agent is a client problem. Separating those
              two saves the most time of anything on this page.
            </p>
          </Step>

          <Step n={6} title="Run it, on something that needs a file">
            <CodeBlock code={'codex'} label="Copy" />
            <p>
              Ask for something that requires reading a file — &quot;read
              README.md and tell me what it says&quot;. A greeting proves text
              flows; only a tool call proves the agent loop works, and that is
              the part with a silent failure mode.
            </p>
          </Step>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Confirming it is really this platform
        </h2>
        <p className="text-sm text-muted-foreground">
          Worth doing once, because a misconfigured client that quietly falls
          back to its vendor looks identical from the chat window.
        </p>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[11rem_1fr]">
          <dt className="font-mono text-muted-foreground">the header</dt>
          <dd>
            Codex prints <code>model: {agentCapability}</code> and{' '}
            <code>provider: rcsl</code> when it starts. No vendor has a model by
            that name, so seeing it is already evidence.
          </dd>
          <dt className="font-mono text-muted-foreground">codex doctor</dt>
          <dd>
            Reports <code>model: {agentCapability} · rcsl</code>,{' '}
            <code>requires OpenAI auth: false</code>, and whether your key
            variable was found.
          </dd>
          <dt className="font-mono text-muted-foreground">Usage</dt>
          <dd>
            The one that cannot be faked. Every served request is a row this
            platform wrote, naming the capability and the model that answered.
            If it is not there, it did not happen here.
          </dd>
        </dl>
        <p className="text-sm text-muted-foreground">
          A warning that model metadata for{' '}
          <code>{agentCapability}</code> was not found is expected and harmless:
          the client is looking your capability up in its own catalogue of
          vendor models and not finding it, which is exactly right.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">Other clients</h2>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[11rem_1fr]">
          <dt className="font-mono text-muted-foreground">Cline, Continue</dt>
          <dd>
            Work unchanged. They speak{' '}
            <code>/v1/chat/completions</code>; give them the base URL above, the
            key, and <code>{agentCapability}</code> as the model.
          </dd>
          <dt className="font-mono text-muted-foreground">OpenAI SDKs</dt>
          <dd>
            Any language. Set the base URL and the key; the capability goes in
            the <code>model</code> argument. See the API page for the request
            shape.
          </dd>
          <dt className="font-mono text-muted-foreground">Claude Code</dt>
          <dd>
            <strong>Not supported.</strong> It speaks Anthropic&apos;s Messages
            API (<code>/v1/messages</code>), which this gateway does not serve,
            and no base URL setting changes that. A translating proxy in front
            of the gateway is the only route today.
          </dd>
          <dt className="font-mono text-muted-foreground">
            Codex in ChatGPT
          </dt>
          <dd>
            <strong>Not possible.</strong> The hosted version cannot be pointed
            at a custom endpoint. The CLI and the desktop app read the
            configuration above; the browser one does not.
          </dd>
        </dl>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          When it goes wrong
        </h2>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[15rem_1fr]">
          <dt className="font-mono text-xs text-muted-foreground">
            wire_api = &quot;chat&quot; is no longer supported
          </dt>
          <dd>Step 3. Set it to {'"responses"'} and restart the client.</dd>

          <dt className="font-mono text-xs text-muted-foreground">
            403 country_not_allowed
          </dt>
          <dd>
            That machine is outside the countries this deployment accepts. A VPN
            exit in the wrong place does this too.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">401</dt>
          <dd>
            Wrong, expired or revoked key — or a CIDR list that does not include
            this machine. The response does not distinguish them on purpose.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            429 part way through a task
          </dt>
          <dd>Step 1. The per-minute limit or the daily quota.</dd>

          <dt className="font-mono text-xs text-muted-foreground">
            503 no_available_model
          </dt>
          <dd>
            Nothing is loaded for that capability. An administrator can see it
            on Models; a capability with one candidate and no fallback answers
            this rather than quietly serving something weaker.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            200, but prose instead of a tool call
          </dt>
          <dd>
            <strong>The one failure nothing reports.</strong> Every layer
            succeeded and the model simply did not call the tool. Try a
            different model before changing anything else — no amount of client
            configuration fixes it.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            Every step is slow to start
          </dt>
          <dd>
            Deliberation is on for that capability. An agent pays it again on
            every round trip; ask an administrator to turn it off on the routing
            policy.
          </dd>
        </dl>
      </section>

      {isLoading ? null : capabilities.includes('code') ? null : (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          This deployment has no <code>code</code> capability yet. An agent works
          against any routable capability, but <code>code</code> is the one an
          administrator sizes for agents — one model, no fallback, deliberation
          off. Ask for it before pointing real work at this.
        </p>
      )}
    </div>
  );
}
