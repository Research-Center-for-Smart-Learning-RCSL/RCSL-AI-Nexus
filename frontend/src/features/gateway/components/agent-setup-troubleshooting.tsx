export function TroubleshootingSection() {
  return (
<section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Failure conditions
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
            The machine is outside the countries this deployment accepts. A VPN
            exit in an unaccepted country produces the same result.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            403 capability_not_issued
          </dt>
          <dd>
            <strong>
              Establish which name was refused before making any change.
            </strong>{' '}
            The key is usually correct and the name that reached the gateway is
            not the one in the configuration file, which is what makes this the
            most costly recurring failure on this deployment. The message names
            what was sent and lists what the key may use.
            <br />
            <strong>
              A client&apos;s own model picker overrides step 3.
            </strong>{' '}
            Codex <code>0.148.0</code> builds that list from{' '}
            <code>GET /v1/models</code> in a format of its own and does not read
            the OpenAI format this gateway answers in, so it falls back to its
            built-in models, none of which this deployment serves. A selection
            made there is refused however correctly{' '}
            <code>model = &quot;code&quot;</code> is written in{' '}
            <code>config.toml</code>. <code>codex -c model=code</code> overrides
            a selection already made.
            <br />
            <strong>
              Some slots do not read <code>model</code> at all.
            </strong>{' '}
            <code>codex-auto-review</code> is sent under its own identifier
            before a command the client intends to escalate, so it is refused
            whatever the configuration states. Because the refused call is the
            review, the observed symptom is the escalated command failing rather
            than a model error, which resembles a filesystem permission fault.
            No grant is required: it is not a capability, so there is no
            capability to issue. Disable the automatic review, or point that
            slot at <code>code</code> where the installed version exposes the
            setting.
            <br />
            <strong>
              A key can be issued with a default capability, which is a trade
              rather than a remedy.
            </strong>{' '}
            An administrator can set <code>default_capability</code> on the key
            to one of the key&apos;s own capabilities, and the gateway then
            serves that instead of refusing whatever name arrives. It can never
            name a capability the key was not issued for. The cost is the loss
            of the signal: a client sending its own model name simply works, and
            the fact that the <code>model</code> line was never in use goes
            undetected. The response carries{' '}
            <code>X-Capability-Defaulted</code> naming what was actually run,
            and the usage record retains what was requested, so the question
            remains answerable afterwards.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">401</dt>
          <dd>
            An incorrect, expired or revoked key, or a CIDR list that does not
            include this machine. The response does not distinguish between them
            by design.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            429 part way through a task
          </dt>
          <dd>
            Step 1, but read <code>error.code</code> first, because the two
            limits sharing this status have opposite remedies.{' '}
            <code>rate_limited</code> is the per-minute limit and is usually the
            client retrying after another failure.{' '}
            <code>quota_exceeded</code> is the token budget; it states how long
            it requires and does not clear on retry. Where a client reports only{' '}
            <em>exceeded retry limit, last status: 429</em>, it has discarded the
            response body; quote the request id it prints. Every refusal is
            stored with the figures it carried, so that id can be looked up on
            the Refusals screen by the account the key belongs to — reading
            one&apos;s own refusals requires no administrator — rather than by
            an administrator reading a container log. The stored record includes
            the wait a <code>429</code> specified, which is otherwise a header
            no longer held by anyone.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            413 context_too_long
          </dt>
          <dd>
            The input exceeded the ceiling: at most 122,880 tokens, counting the
            tool definitions and every replayed turn, and lower where a smaller
            model is serving the capability. The refusal names the figure it was
            judged against. It is not a quota, and waiting does not clear it.
            Codex reports it as{' '}
            <em>unexpected status 413 Payload Too Large</em> and will retry it
            several times first, to no effect.
            <br />
            <strong>Read the composition before choosing a remedy</strong>,
            because the three components have different remedies and only one of
            them is to start again. For a conversation that has accumulated:{' '}
            <strong>start a new one</strong>, or have the agent summarise and
            continue from the summary. For a single very large message: stop
            reading that file in. For tool definitions occupying most of the
            budget: <strong>reduce the client&apos;s tool list</strong>, since
            they are resent on every turn and a new conversation therefore
            receives the identical 413 on its first request. A share that
            remains constant while the message count changes indicates this
            case; on a machine running the ChatGPT desktop application it is
            usually that application&apos;s own tools arriving through the
            shared configuration directory, described above.
            <br />
            The count is the model&apos;s own rather than an estimate: the
            prompt is tokenized with the vocabulary and chat template of the
            model that would have read it, so the figure in the refusal is the
            one that model would have charged. The response states the basis in{' '}
            <code>basis</code>, of which there are three:{' '}
            <code>tokenizer</code> for a true count, <code>estimate</code> for
            the character-width fallback applied to a model with no vocabulary
            on this host, and <code>lower_bound</code> for the inexpensive guard
            that runs before a model has been selected. The guard refuses only
            what no tokeniser could bring under the ceiling, so on that basis the
            true figure is above the number shown. The estimate ran roughly 20%
            to 60% high on ordinary content and refused at least one
            conversation that would have fitted; a <code>tokenizer</code> figure
            does not.
            <br />
            <strong>
              Codex does not display the response body, so read the error
              directly.
            </strong>{' '}
            The response carries <code>composition</code>, which states how the
            count divided across messages, prior tool calls and tool
            definitions, and what share the largest single turn occupied. That
            is the quickest means of distinguishing an accumulated conversation
            from a single file occupying most of the budget. Where the client
            has discarded it, quote the request id it printed: the same
            breakdown is stored with the refusal and can be read back from the
            Refusals screen without recourse to a container log.
            <br />
            <strong>
              Budget from where a conversation begins, not from zero.
            </strong>{' '}
            Three sessions measured on this deployment began at approximately
            42,000 tokens before any work was done — tool definitions, the
            agent&apos;s instruction file, and whatever material opened the
            session — and the turns that wrote files cost around 10,000 tokens
            each. Against the 122,880-token ceiling that leaves roughly 80,000
            tokens, or about eight such turns. All three figures are properties
            of the client, and raising the ceiling only extends how long a
            session runs before it stops.
            <br />
            The ceiling is reached sooner than a character count suggests when
            working in Chinese: measured against the model now serving this
            deployment, Traditional Chinese costs approximately one token per
            1.5 characters against 4.4 for English, and a token is the unit the
            ceiling counts.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            503 no_available_model
          </dt>
          <dd>
            Nothing is loaded for that capability. An administrator can confirm
            this on Models. A capability with one candidate and no fallback
            returns this rather than serving something weaker.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            200, but prose instead of a tool call
          </dt>
          <dd>
            <strong>The one failure that nothing reports.</strong> Every layer
            succeeded and the model did not call the tool. Try a different model
            before changing anything else; no amount of client configuration
            corrects it.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            The answer stops mid-sentence
          </dt>
          <dd>
            A model&apos;s context window holds the prompt and the answer
            together, and an agent replays the entire conversation on every
            turn, so the room remaining to answer in contracts as a task
            proceeds. The window is now 262,144 tokens against a 122,880-token
            ceiling on what may be sent, so the room to answer in is what
            remains of more than twice the largest permitted prompt, and a
            truncated reply now terminates as <code>response.incomplete</code>.
            Where this is still observed, the cause is the output ceiling rather
            than the window, and the response states as much.
          </dd>

          <dt className="font-mono text-xs text-muted-foreground">
            Every step is slow to start
          </dt>
          <dd>
            Deliberation is enabled for that capability. An agent incurs the
            cost on every round trip; ask an administrator to disable it on the
            routing policy.
          </dd>
        </dl>
      </section>
  );
}
