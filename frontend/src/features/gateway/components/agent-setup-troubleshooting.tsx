

export function TroubleshootingSection() {
  return (
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

          <dt className="font-mono text-xs text-muted-foreground">
            403 capability_not_issued
          </dt>
          <dd>
            <strong>Read which name was refused before anything else.</strong>{' '}
            The key is usually right and the name that reached the gateway is
            not the one in your file, which is what makes this the most
            expensive recurring failure here. The message names what was sent
            and lists what the key may use.
            <br />
            <strong>
              Your client&apos;s own model picker overrides step 3.
            </strong>{' '}
            Codex <code>0.148.0</code> builds that list from{' '}
            <code>GET /v1/models</code> in a shape of its own and does not read
            the OpenAI one this gateway answers in, so it falls back to its
            built-in models — none of which this deployment serves. Anything
            chosen there is refused however correctly{' '}
            <code>model = &quot;code&quot;</code> is written in{' '}
            <code>config.toml</code>. <code>codex -c model=code</code> overrides
            a selection already made.
            <br />
            <strong>
              Some slots never read <code>model</code> at all.
            </strong>{' '}
            <code>codex-auto-review</code> is sent under its own slug before a
            command the client wants to escalate, so it is refused whatever your
            configuration says — and because the refused call is the review,
            what you see is the escalated command failing rather than a model
            error, which reads convincingly as a filesystem permission problem.
            Nothing needs granting: it is not a capability, so there is no
            capability to issue. Turn the auto-review off, or point that slot at{' '}
            <code>code</code> if your version exposes the setting.
            <br />
            <strong>
              A key can be issued with a default capability, which is a trade
              rather than a fix.
            </strong>{' '}
            An administrator can set <code>default_capability</code> on the key
            to one of its own capabilities, and the gateway then serves that
            instead of refusing whatever name arrives. It can never name a
            capability the key was not issued for. What it costs is the signal:
            a client sending its own model name simply works, and nobody
            discovers that the <code>model</code> line was never in use. The
            response carries <code>X-Capability-Defaulted</code> with what
            actually ran, and the usage record keeps what was asked for, so the
            question stays answerable afterwards.
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
            the body; quote the request id it prints. Since 2026-08-18 every
            refusal is stored with the figures it carried, so that id can
            be looked up on the Refusals screen by the account the key belongs
            to — reading your own refusals needs no administrator — rather than
            by anyone reading a container log — including the wait a <code>429</code> asked for,
            which is otherwise a header nobody still has.
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
            Since 2026-08-17 the count is the model&apos;s own, not an estimate:
            your prompt is tokenized with the vocabulary and chat template of the
            model that would have read it, so the figure in the refusal is the
            one that model would have charged. The response says which in{' '}
            <code>basis</code>, and there are three of them:{' '}
            <code>tokenizer</code> for a real count, <code>estimate</code> for
            the character-width fallback a model with no vocabulary on this host
            still gets, and <code>lower_bound</code> for the cheap guard that
            runs before a model has been chosen at all — it refuses only what no
            tokeniser could bring under the ceiling, so on that basis the true
            figure is somewhere above the number shown. The estimate ran roughly 20% to 60%
            high on ordinary content and refused at least one conversation that
            would have fitted; a <code>tokenizer</code> figure does not.
            <br />
            <strong>Codex hides the body, so read the error yourself.</strong>{' '}
            The response carries <code>composition</code>, which says how the
            count split across your messages, prior tool calls and tool
            definitions, and what share the largest single turn took — the
            fastest way to tell &quot;the conversation grew&quot; from &quot;one
            file is 97% of it&quot;. If your client has swallowed it, quote the
            request id it printed: the same breakdown is stored with the
            refusal, and an administrator can read it back from the Refusals
            screen without going near a container log.
            <br />
            <strong>Budget from where a conversation starts, not from zero.</strong>{' '}
            Three sessions measured here on 2026-08-17 began at about 42,000
            tokens before any work — tool definitions, the agent&apos;s
            instruction file, and whatever was pasted to open with — and the
            turns that wrote files cost around 10,000 tokens each. Against the
            122,880-token ceiling that leaves roughly 80,000 tokens, or about
            eight such turns. This said four until 2026-08-18, computed against
            the 98,304 ceiling of the day before and on an estimator that ran
            roughly 20% to 60% high. All three of those are the client&apos;s, and raising the
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
            succeeded and the model did not call the tool. Try a
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
  );
}
