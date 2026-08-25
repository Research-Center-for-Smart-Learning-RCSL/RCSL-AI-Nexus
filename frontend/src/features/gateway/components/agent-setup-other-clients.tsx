
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
            Supported without modification. They speak{' '}
            <code>/v1/chat/completions</code>; supply the base URL above, the
            key, and <code>{agentCapability}</code> as the model.
          </dd>
          <dt className="font-mono text-muted-foreground">OpenAI SDKs</dt>
          <dd>
            Supported in any language. Set the base URL and the key; the
            capability is passed in the <code>model</code> argument. The API
            reference states the request structure.
          </dd>
          <dt className="font-mono text-muted-foreground">Claude Code</dt>
          <dd>
            <strong>Not supported.</strong> It speaks Anthropic&apos;s Messages
            API (<code>/v1/messages</code>), which this gateway does not serve,
            and no base URL setting alters that. A translating proxy in front of
            the gateway is the only available route.
          </dd>
          <dt className="font-mono text-muted-foreground">
            Codex in the ChatGPT app
          </dt>
          <dd>
            <strong>
              Supported, subject to the volume of tool definitions the
              application injects.
            </strong>{' '}
            Local surfaces using the same Codex home read the same user
            configuration, so completing step 3 configures the application as
            well; this has been observed on macOS. OpenAI documents the native
            Windows App/CLI sharing and the separate WSL default in its{' '}
            <a
              className="underline underline-offset-2"
              href="https://learn.chatgpt.com/docs/windows/windows-app#share-config-auth-and-sessions-with-wsl"
              rel="noreferrer"
              target="_blank"
            >
              Windows App guide
            </a>
            .{' '}
            <strong>The sharing operates in both directions.</strong> The
            application owns that directory: it rewrites the file, and it
            supplies the CLI with its own tool surface, which is resent on every
            turn.
            <br />
            <strong>
              Two Windows machines, both running application build
              26.810.52044.
            </strong>{' '}
            The first carried a computer-use runtime and{' '}
            <strong>five bundled plugins</strong>, and sent{' '}
            <strong>286 tool definitions</strong> — an estimated 122,870 tokens,
            and approximately 99,000 tokens when counted with the model&apos;s
            own vocabulary, which leaves room for a first message and very
            little thereafter. The second carried <strong>two plugins</strong>{' '}
            and operated for days without incident. The determining factor is a
            quantity rather than a property of the application, and the quantity
            that matters is the local one:{' '}
            <strong>one successful request records the composition</strong>, and
            a machine that already refuses every request cannot be measured.
            <br />
            <strong>The condition is difficult to diagnose.</strong>{' '}
            <code>codex mcp list</code> reported no servers while a server was
            present in the file; the file read as clean and, fifteen minutes
            later, read with five plugins; quitting the application had no
            effect, because the CLI reads what the application has already
            written; and a provider block written by hand was absent at the next
            read.
            <br />
            <strong>Give the CLI its own directory.</strong> Point{' '}
            <code>CODEX_HOME</code> at a folder containing only the step 3
            configuration, set per shell rather than machine-wide, since a
            machine-wide value moves the application as well. Reverting requires
            one further step: after the lines are removed, the application can
            still fail at startup on a conversation created against the former
            provider, and deleting that conversation is what clears the
            condition. Leaving the{' '}
            <code>[model_providers.rcsl]</code> block in place
            avoids the error entirely.
            <br />
            <strong>
              Both figures above are qualified by a build for a reason.
            </strong>{' '}
            The application updates itself and arrives with plugins that were
            not installed deliberately — one of these machines acquired a sixth
            overnight — so a tool count holds only for the build and plugin set
            it was measured on.
          </dd>
          <dt className="font-mono text-muted-foreground">
            Codex on the web
          </dt>
          <dd>
            <strong>Not possible.</strong> <code>chatgpt.com/codex</code> runs
            on OpenAI&apos;s machines, reads no local file, and offers no
            setting for a custom endpoint. The local surfaces — CLI, IDE
            extension, desktop application — all read the configuration above;
            the browser surface cannot.
          </dd>
        </dl>
      </section>
  );
}
