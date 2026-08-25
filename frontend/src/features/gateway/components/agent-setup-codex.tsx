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

          <Step n={2} title="Download the Windows switcher or install the CLI">
            <CodeBlock
              code={String.raw`$archive = Join-Path $env:TEMP 'RCSL-AI-Nexus-main.zip'
$toolsRoot = Join-Path $env:LOCALAPPDATA 'RCSL-AI-Nexus\client-tools'
Invoke-WebRequest 'https://github.com/Research-Center-for-Smart-Learning-RCSL/RCSL-AI-Nexus/archive/refs/heads/main.zip' -OutFile $archive
Expand-Archive -LiteralPath $archive -DestinationPath $toolsRoot -Force`}
              label="Copy (download Windows App tools)"
            />
            <CodeBlock code={'npm install -g @openai/codex'} label="Copy (CLI)" />
            <p>
              The first command downloads the published repository archive to a
              user-local tools directory, so it does not assume the operator can
              read the deployment repository. Inspect the downloaded scripts
              before running them. The switcher installs the Store App
              automatically when it is absent. Node.js is required only for the
              separately installed CLI.
            </p>
          </Step>

          <Step n={3} title="Write the configuration">
            <p>
              <code>~/.codex/config.toml</code>, or{' '}
              <code>%USERPROFILE%\.codex\config.toml</code> on Windows:
            </p>
            <CodeBlock
              code={`model = "${agentCapability}"
model_provider = "rcsl_nexus_switcher"

[model_providers.rcsl_nexus_switcher]
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
            <p>
              The Windows App switcher writes this provider block and selection
              for you. Treat this example as the wire-level reference; do not
              hand-edit it while the App is running.
            </p>
          </Step>

          <Step n={4} title="Provide the key to the selected client">
            <CodeBlock
              code={'export RCSL_API_KEY=nx_live_...'}
              label="Copy (macOS, Linux)"
            />
            <CodeBlock
              code={
                String.raw`powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\RCSL-AI-Nexus\client-tools\RCSL-AI-Nexus-main\scripts\windows\codex-app\Start-CodexAppSwitcher.ps1"`
              }
              label="Copy (Windows App switcher)"
            />
            <p>
              On Windows, paste the key into the switcher&apos;s masked field. It
              validates the key and passes it only to the newly launched App
              process. It does not use <code>setx</code>, write the key into
              TOML, or change the ChatGPT sign-in. The same GUI restores the
              prior OpenAI provider selection.
            </p>
          </Step>

          <Step n={5} title="Verify the selected client path">
            <CodeBlock
              code={`curl ${baseUrl}/v1/models -H "Authorization: Bearer $RCSL_API_KEY"`}
              label="Copy (CLI on macOS or Linux)"
            />
            <p>
              The Windows App GUI performs the same authenticated catalogue
              check before changing configuration. Its Doctor button rechecks
              the exact URL and capability selected in the GUI and asks for the
              key in a masked dialog. The shell command applies only to a shell
              where step 4 exported the variable; the App-scoped key is not
              available to <code>curl</code> or a separately launched CLI.
            </p>
          </Step>

          <Step n={6} title="Run a new task that requires a file">
            <CodeBlock code={'codex'} label="Copy (CLI)" />
            <p>
              In the App, create a new task after switching. In either surface,
              request something that requires reading a file, such as
              &quot;read README.md and summarise it&quot;. A greeting
              establishes only that text flows; a tool call establishes that the
              agent loop works, which is the part with a silent failure mode.
            </p>
          </Step>
        </div>
      </section>
  );
}
