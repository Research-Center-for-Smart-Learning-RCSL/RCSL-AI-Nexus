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
                <strong>Requests per minute.</strong> An agent makes one
                request per step and a task is tens of steps, though in practice
                even a busy minute rarely passes twenty. <strong>
                  A <code>429</code> mid-task is more often the client retrying
                  after a failure than this limit being reached
                </strong>{' '}
                — check Usage before raising it, or the change lands on the
                wrong limit and the failure continues.
              </li>
              <li>
                <strong>Daily token quota.</strong> An agent replays the whole
                conversation every turn, and prompt tokens count. Consumption
                grows roughly with the square of a task&apos;s length, not
                linearly. Size it generously — measured on 2026-08-14, one
                Codex session ran{' '}
                <strong>sixteen requests in eleven minutes</strong>, its context
                growing from 38,738 tokens to 61,920 with every turn charged the
                whole of it. That key&apos;s whole day came to twenty requests
                and <strong>1.03 million tokens</strong>, of which 99.6% was
                prompt and 4,564 tokens were generated output. A one-million
                quota is one session, not one day.
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
              <strong>Node.js is required.</strong> Install it from nodejs.org,
              or <code>winget install OpenJS.NodeJS.LTS</code> on Windows, then
              reopen the terminal. On Windows PowerShell may refuse to run{' '}
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
            <p>
              <strong>
                <code>env_key</code> is the <em>name</em> of an environment
                variable, not the key.
              </strong>{' '}
              Leave it as <code>RCSL_API_KEY</code> and put the key in that
              variable at step 4. Pasting <code>nx_live_...</code> here does not
              work, and it writes a credential into a file that gets copied,
              committed and shared.
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
  );
}
