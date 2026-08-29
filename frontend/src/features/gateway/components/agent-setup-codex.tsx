import { CodeBlock } from '@/components/composed/code-block';
import { Step } from './agent-setup-step';

type CodexConfigurationSectionProps = {
  baseUrl: string;
  agentCapability: string;
};

/**
 * Same-origin on purpose. `next.config.js` forwards `/admin/:path*` to the
 * admin API keeping the prefix, so the browser's session cookie goes with it
 * and the bytes come from the deployed image.
 *
 * This replaced a copy-paste `Invoke-WebRequest` of the whole repository
 * archive from GitHub `main`, which delivered a deployment's worth of files to
 * get four, named no version anybody could refer to, and sent an operator who
 * trusts this platform to a different origin for a script that will hold their
 * key. `tests/unit/test_route_prefix.py` pins the path.
 */
const CLIENT_TOOLS_DOWNLOAD_PATH = '/admin/client-tools/windows-codex-app';

export function CodexConfigurationSection({ baseUrl, agentCapability }: CodexConfigurationSectionProps) {
  return (
<section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Codex setup for this deployment
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
            <p>
              <a
                className="inline-flex items-center rounded-md border border-border bg-muted/40 px-3 py-2 font-medium underline underline-offset-2"
                download
                href={CLIENT_TOOLS_DOWNLOAD_PATH}
              >
                Download the Windows App tools (.zip)
              </a>
            </p>
            <p>
              Served by this deployment, from the revision it is running, over
              the session you are already signed in to. Unzip it anywhere you
              can read, and inspect the scripts before running them: they will
              hold your API key.
            </p>
            <CodeBlock code={'npm install -g @openai/codex'} label="Copy (CLI)" />
            <p>
              The switcher installs the Store App automatically when it is
              absent. Node.js is required only for the separately installed CLI.
              OpenAI publishes the{' '}
              <a
                className="underline underline-offset-2"
                href="https://learn.chatgpt.com/docs/windows/windows-app#download-the-chatgpt-desktop-app"
                rel="noreferrer"
                target="_blank"
              >
                Windows App installation command
              </a>
              . Package identity and executable discovery remain guarded
              implementation assumptions.
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
              The current OpenAI{' '}
              <a
                className="underline underline-offset-2"
                href="https://learn.chatgpt.com/docs/config-file/config-reference"
                rel="noreferrer"
                target="_blank"
              >
                configuration reference
              </a>{' '}
              documents only <code>responses</code>. This project observed the
              client refusing <code>wire_api = &quot;chat&quot;</code> at its
              February 2026 compatibility boundary; that date is project
              evidence, not an OpenAI compatibility promise.
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
              Leave it as <code>RCSL_API_KEY</code>. The CLI reads that named
              environment variable; the Windows switcher supplies it only to
              the App process it launches. A key pasted here does not work, and
              it writes a credential into a file that is copied, committed and
              shared.
            </p>
            <p>
              This is the manual CLI provider. The Windows App switcher writes
              an isolated <code>rcsl_nexus_switcher</code> provider instead, so
              it cannot overwrite this table. Treat the example as the
              wire-level reference; do not hand-edit App configuration while
              the App is running. The fields follow OpenAI&apos;s{' '}
              <a
                className="underline underline-offset-2"
                href="https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers"
                rel="noreferrer"
                target="_blank"
              >
                custom model-provider schema
              </a>
              .
            </p>
          </Step>

          <Step n={4} title="Provide the key to the selected client">
            <CodeBlock
              code={'export RCSL_API_KEY=nx_live_...'}
              label="Copy (macOS, Linux)"
            />
            <CodeBlock
              code={
                String.raw`powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\RCSL-AI-Nexus\client-tools\Start-CodexAppSwitcher.ps1"`
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
