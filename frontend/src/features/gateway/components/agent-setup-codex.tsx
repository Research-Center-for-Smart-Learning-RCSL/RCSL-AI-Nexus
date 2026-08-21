import { CodeBlock } from '@/components/composed/code-block';
import { Step } from './agent-setup-step';

type CodexConfigurationSectionProps = {
  baseUrl: string;
  agentCapability: string;
};

export function CodexConfigurationSection({ baseUrl, agentCapability }: CodexConfigurationSectionProps) {
  return (
<section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Codex, verified against this deployment
        </h2>
        <p className="text-sm text-muted-foreground">
          Six steps. Two of them carry a setting whose default is unsuitable and
          which fails in a manner that resembles a different fault.
        </p>

        <div className="space-y-5 pt-1">
          <Step n={1} title="Issue a key for one capability">
            <p>
              On <strong>API keys</strong>, issue a key scoped to{' '}
              <code>{agentCapability}</code> and to nothing else. Two defaults
              are unsuitable for an agent, and both fail part way through a
              task:
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <strong>Requests per minute.</strong> An agent issues one
                request per step and a task comprises tens of steps, although in
                practice a busy minute rarely exceeds twenty.{' '}
                <strong>
                  A <code>429</code> during a task is more often the client
                  retrying after another failure than this limit being reached.
                </strong>{' '}
                Consult Usage before raising it, or the change is applied to the
                wrong limit and the failure persists.
              </li>
              <li>
                <strong>Daily token quota.</strong> An agent replays the entire
                conversation on every turn, and prompt tokens are counted.
                Consumption grows approximately with the square of a task&apos;s
                length rather than linearly. Size the quota generously. Measured
                on this deployment, one Codex session issued{' '}
                <strong>sixteen requests in eleven minutes</strong>, its context
                growing from 38,738 tokens to 61,920, with every turn charged
                the whole of it. That key&apos;s consumption for the day was
                twenty requests and <strong>1.03 million tokens</strong>, of
                which 99.6% was prompt and 4,564 tokens were generated output. A
                one-million quota is one session, not one day.
              </li>
            </ul>
            <p>
              Leave <strong>allowed CIDRs</strong> empty unless the machine has
              a fixed public address. A dynamic address changes on reconnection,
              and the resulting <code>401</code> does not state the reason:
              naming the rule that refused a request would disclose the
              perimeter to anyone probing it.
            </p>
          </Step>

          <Step n={2} title="Install the client">
            <CodeBlock code={'npm install -g @openai/codex'} label="Copy" />
            <p>
              <strong>Node.js is required.</strong> Install it from nodejs.org,
              or with <code>winget install OpenJS.NodeJS.LTS</code> on Windows,
              then reopen the terminal. On Windows, PowerShell may refuse to run{' '}
              <code>npm</code> until local scripts are permitted once:{' '}
              <code>Set-ExecutionPolicy -Scope CurrentUser RemoteSigned</code>.
              That setting is per-user, requires no administrator, and is the
              value Microsoft recommends for a workstation.
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
              Codex withdrew support for Chat Completions in February 2026 and
              refuses to start on <code>wire_api = &quot;chat&quot;</code>. Any
              instructions still specifying <code>&quot;chat&quot;</code>
              predate that change.
            </p>
            <p>
              <strong>
                <code>model</code> takes a capability, not a model name.
              </strong>{' '}
              Use <code>{agentCapability}</code>, never the name of the model
              serving it. This is the platform&apos;s one substantive divergence
              from other providers.
            </p>
            <p>
              <strong>
                <code>env_key</code> is the <em>name</em> of an environment
                variable, not the key itself.
              </strong>{' '}
              Leave it as <code>RCSL_API_KEY</code> and place the key in that
              variable at step 4. A key pasted here does not work, and it writes
              a credential into a file that is copied, committed and shared.
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
              On Windows, <code>setx</code> writes the variable for future
              processes only.{' '}
              <strong>Close the terminal and open a new one</strong>, or the
              client will not see it.
            </p>
          </Step>

          <Step n={5} title="Verify the platform before involving the agent">
            <CodeBlock
              code={`curl ${baseUrl}/v1/models -H "Authorization: Bearer $RCSL_API_KEY"`}
              label="Copy the check"
            />
            <p>
              A list naming the capability establishes that the whole path
              works: network, perimeter, key and routing. A failure at this step
              is a deployment fault; a failure only within the agent is a client
              fault. Distinguishing the two is the single most economical step
              on this page.
            </p>
          </Step>

          <Step n={6} title="Run it against a task that requires a file">
            <CodeBlock code={'codex'} label="Copy" />
            <p>
              Request something that requires reading a file, such as
              &quot;read README.md and summarise it&quot;. A greeting
              establishes only that text flows; a tool call establishes that the
              agent loop works, which is the part with a silent failure mode.
            </p>
          </Step>
        </div>
      </section>
  );
}
