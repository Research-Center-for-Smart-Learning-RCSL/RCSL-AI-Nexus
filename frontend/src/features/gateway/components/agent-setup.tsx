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
 * its own, because both read `~/.codex/config.toml`. **What is written here as
 * a limit needs testing at least as much as what is written here as a step.**
 *
 * And on 2026-08-17 the same line cut a third way: what is written here as
 * *working* goes stale too. "Works, and needs no second setup" was true of the
 * direction that had been tested and false of the machine in front of us,
 * where the app's own tool surface reached the CLI through that shared file and
 * made every request too large to send before a word of it was typed. One
 * sentence of good news had been carrying an untested claim about the
 * conditions under which it holds.
 */

import { useRef } from 'react';

import { CodeBlock } from '@/components/composed/code-block';
import { ExportMarkdown } from '@/components/composed/export-markdown';
import { useAssistantSurface } from '@/features/assistant/context';
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
                — check Usage before raising it, or you will change the wrong
                thing and still be stuck.
              </li>
              <li>
                <strong>Daily token quota.</strong> An agent replays the whole
                conversation every turn, and prompt tokens count. Consumption
                grows roughly with the square of a task&apos;s length, not
                linearly. Size it generously — a measured Codex session on
                2026-08-14 ran twenty requests in eleven minutes and spent{' '}
                <strong>1.03 million tokens</strong>, of which 99.6% was prompt:
                the context grew from 38k to 62k and every turn paid for all of
                it. A one-million quota is one session, not one day.
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
        <h2 className="font-heading text-base font-semibold">
          Going back, and keeping both
        </h2>
        <p className="text-sm text-muted-foreground">
          Step 3 changes the client&apos;s <em>default</em>, which is why the
          desktop app followed it across. Undoing that is a matter of the same
          file — there is nothing to uninstall, and nothing on this platform to
          disconnect.
        </p>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[11rem_1fr]">
          <dt className="font-mono text-muted-foreground">go back</dt>
          <dd>
            Delete the <code>model</code> and <code>model_provider</code> lines
            from <code>~/.codex/config.toml</code>. The client returns to its
            own default. The <code>[model_providers.rcsl]</code> block can stay
            — it describes a provider, and nothing selects it once those two
            lines are gone.{' '}
            <strong>
              Restart the desktop app afterwards; it reads the file at startup.
            </strong>{' '}
            You may need <code>codex login</code> to use OpenAI again, since
            pointing here never required it.
          </dd>
          <dt className="font-mono text-muted-foreground">keep both</dt>
          <dd>
            Better than switching back and forth. Put the provider block in{' '}
            <code>~/.codex/rcsl.config.toml</code> instead, leave{' '}
            <code>config.toml</code> alone, and run{' '}
            <CodeBlock code={'codex --profile rcsl'} label="Copy" /> Plain{' '}
            <code>codex</code> stays on the default. Note this is a{' '}
            <strong>separate file</strong> per profile in{' '}
            <code>0.147.0</code>, not a <code>[profiles.x]</code> table inside{' '}
            <code>config.toml</code> as older guides show — check{' '}
            <code>codex --help</code> against your own version.
          </dd>
          <dt className="font-mono text-muted-foreground">just once</dt>
          <dd>
            <CodeBlock
              code={`codex -c model_provider=rcsl -c model=${agentCapability}`}
              label="Copy"
            />
            Nothing is written to any file. Useful for proving the platform
            half works without committing the machine to it.
          </dd>
          <dt className="font-mono text-muted-foreground">really disconnect</dt>
          <dd>
            <strong>Revoke the key</strong>, on API keys. Everything above is a
            setting on a machine you control, and a copy of the configuration
            on some other machine keeps working. Revoking is the only one of
            these that this platform enforces, and the only one that holds if
            the key has gone somewhere you did not intend.
          </dd>
        </dl>
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
            the <code>model</code> argument. See the API reference for the request
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
            Codex in the ChatGPT app
          </dt>
          <dd>
            <strong>
              The app follows the CLI across, and on a machine where it is
              installed that is the problem rather than the convenience.
            </strong>{' '}
            Both read <code>~/.codex/config.toml</code>, so finishing step 3
            points the app here too — observed on macOS on 2026-08-09, after an
            earlier version of this page called it impossible.{' '}
            <strong>The sharing runs the other way as well.</strong> The app
            owns that directory: it rewrites the file, and it hands the CLI its
            own tool surface. Measured on Windows on 2026-08-17, app build
            26.810.52044: every request carried{' '}
            <strong>286 tool definitions, an estimated 122,870 tokens</strong> —
            more than this whole ceiling on its own, so nothing could be sent at
            any conversation length. The source was the app&apos;s computer-use
            and browser runtime plus five bundled plugins.
            <br />
            It hid well, and each clue read as innocence:{' '}
            <code>codex mcp list</code> reported none while the server was in
            the file, the file read clean and then read with five plugins
            fifteen minutes later, and quitting the app changed nothing because
            the CLI reads what the app already wrote. A provider block written
            by hand was gone by the next read.
            <br />
            <strong>Give the CLI its own directory instead.</strong> Point{' '}
            <code>CODEX_HOME</code> at a folder holding only the step 3
            configuration, per shell rather than machine-wide — a global one
            moves the app too. Undoing it also takes one more step than it
            looks: after removing those lines the app can still fail at startup
            on a conversation created against the old provider, and deleting
            that conversation is what clears it.
          </dd>
          <dt className="font-mono text-muted-foreground">
            Codex on the web
          </dt>
          <dd>
            <strong>Not possible</strong>, and this is the one that genuinely
            is not. <code>chatgpt.com/codex</code> runs on OpenAI&apos;s
            machines, reads no file on yours, and has no setting for a custom
            endpoint. Local surfaces — CLI, IDE extension, desktop app — all
            read the configuration above; the browser one cannot.
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
          <dd>
            Step 1 — but read <code>error.code</code> first, because the two
            limits sharing this status have opposite fixes.{' '}
            <code>rate_limited</code> is the per-minute one and is usually the
            client retrying after some other failure. <code>quota_exceeded</code>{' '}
            is the token budget, which says how long it needs and does not come
            back by retrying. If your client only reports{' '}
            <em>exceeded retry limit, last status: 429</em>, it has swallowed
            the body; quote the request id it prints and an administrator can
            find the refusal in the gateway log.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            413 context_too_long
          </dt>
          <dd>
            Your input outgrew the ceiling — at most 122,880 tokens, counting
            your tool definitions and every replayed turn, and lower when a
            smaller model is serving your capability. The refusal names the
            figure it judged against. It is not a quota and waiting does not
            clear it. Codex reports it as{' '}
            <em>unexpected status 413 Payload Too Large</em> and will retry it
            several times first, which changes nothing.
            <br />
            <strong>Read the composition before choosing a fix</strong>, because
            the three parts have different remedies and only one of them is
            &quot;start again&quot;. A conversation that accumulated:{' '}
            <strong>start a new one</strong>, or have the agent summarise and
            continue from the summary. One enormous message: stop reading that
            file in. Tool definitions taking most of it:{' '}
            <strong>trim your client&apos;s tool list</strong> — they are resent
            on every turn, so a new conversation gets the identical 413 on its
            first request. A share that stays identical while your message count
            moves is this case, and on a machine with the ChatGPT desktop app it
            is usually the app&apos;s own tools arriving through the shared
            configuration directory; see Codex in the ChatGPT app above.
            <br />
            The count is an estimate from character widths, and a deliberately
            careful one — it can refuse a conversation that would have fitted.
            Reading one large file repeatedly is what usually reaches it.
            <br />
            <strong>Codex hides the body, so read the error yourself.</strong>{' '}
            The response carries <code>composition</code>, which says how the
            estimate split across your messages, prior tool calls and tool
            definitions, and what share the largest single turn took — the
            fastest way to tell &quot;the conversation grew&quot; from &quot;one
            file is 97% of it&quot;. If your client has swallowed it, quote the
            request id it printed and an administrator can read the same
            breakdown from the gateway log.
            <br />
            <strong>Budget from where a conversation starts, not from zero.</strong>{' '}
            Three sessions measured here on 2026-08-17 began at about 42,000
            tokens before any work — tool definitions, the agent&apos;s
            instruction file, and whatever was pasted to open with — and the
            turns that wrote files cost around 10,000 each, which is four turns
            of room. All three of those are the client&apos;s, and raising the
            ceiling only changes how long a session runs before it stops.
            <br />
            Reached sooner than the character count suggests if you work in
            Chinese: measured against the model now serving this deployment,
            Traditional Chinese costs about one token per 1.5 characters against
            4.4 for English, and a token is what the ceiling counts.
          </dd>

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
            The answer stops mid-sentence
          </dt>
          <dd>
            <strong>Fixed on 2026-08-09, in both halves.</strong> A model&apos;s
            context window holds the prompt and the answer together, and an
            agent replays the whole conversation every turn — so the room left
            to answer in shrank as a task went on. Measured here that day: a
            prompt of 32231 tokens and a reply of 537, against a 32768-token
            window. The reply was exactly what was left, and the platform
            reported it as a normal completion, so the client had nothing to
            show. The window is now 262144 tokens against a 122880-token
            ceiling on what you may send, so the room to answer in is what is
            left of more than twice your largest possible prompt — and a
            truncated reply now ends as{' '}
            <code>response.incomplete</code>. If you still see this, it is the
            output ceiling rather than the window, and the response says so.
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
    </div>
  );
}
