

type OtherClientsSectionProps = {
  agentCapability: string;
};

export function OtherClientsSection({ agentCapability }: OtherClientsSectionProps) {
  return (
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
              It follows the CLI across, and whether that is the convenience or
              the problem depends on how much the app has enabled.
            </strong>{' '}
            Both read <code>~/.codex/config.toml</code>, so finishing step 3
            points the app here too — observed on macOS on 2026-08-09, after an
            earlier version of this page called it impossible.{' '}
            <strong>The sharing runs the other way as well.</strong> The app
            owns that directory: it rewrites the file, and it hands the CLI its
            own tool surface — which is resent on every turn.
            <br />
            <strong>Two Windows machines, same app build 26.810.52044.</strong>{' '}
            One carried a computer-use runtime and{' '}
            <strong>five bundled plugins</strong>, and sent{' '}
            <strong>286 tool definitions, an estimated 122,870 tokens</strong> —
            more than the entire ceiling as it stood that day (98,304), so
            nothing could be sent at any conversation length. Both figures have
            moved since: the ceiling is 122,880, and counted with the model&apos;s
            own vocabulary rather than estimated, the same payload is about
            99,000 real tokens — which leaves room for a first message and very
            little after it. The other carried{' '}
            <strong>two plugins</strong> and worked for days. Between 2026-08-17
            and 2026-08-18 this page said a machine with the app could not be
            connected at all, generalised from the first of those two. It is a
            quantity, not a yes or no, and the one worth knowing is your own:{' '}
            <strong>one successful request logs the composition</strong>, and a
            machine already refusing everything is too late to measure.
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
            that conversation is what clears it — leaving the{' '}
            <code>[model_providers.rcsl]</code> block in place avoids that
            error entirely.
            <br />
            <strong>Both figures above carry a build for a reason.</strong> The
            app updates itself and arrives with plugins nobody installed — one
            of these machines gained a sixth overnight — so a tool count is only
            true of the build and the plugin set it was taken on.
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
  );
}
