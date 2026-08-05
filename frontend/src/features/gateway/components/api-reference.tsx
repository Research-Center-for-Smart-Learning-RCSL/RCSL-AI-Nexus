'use client';

import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { CodeBlock } from '@/components/composed/code-block';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';
import { useAssistantSurface } from '@/features/assistant/context';

/**
 * The public API documentation security.md §4.4 promised.
 *
 * `/openapi.json` and `/docs` are disabled on the gateway — permanently in
 * production, since `expose_openapi` is `and not is_production` — so this is
 * the only description of the wire contract an integrator will ever see. That
 * is a deliberate trade (§4.4 prefers writing documentation over exposing
 * internal schemas), and it is a trade only if the documentation exists.
 *
 * Rendered from the live deployment rather than written as prose, so the base
 * URL and the capability list are the real ones. A page that hardcoded
 * `llmapi.rcsl.online` would be wrong on every other deployment and nobody
 * would notice.
 *
 * Audited field by field against `routers/chat.py`, `schemas/chat_schemas.py`,
 * `sse.py` and `errors.py` on 2026-07-30, which found five omissions rather
 * than any inaccuracy: grounding, the silently ignored OpenAI fields, what a
 * mid-stream failure looks like, `prompt_tokens`, and four reachable error
 * codes. All closed on 2026-08-03. The rule the audit worked to, and the one to
 * keep: **anything an integrator would only discover by being surprised belongs
 * here**, including the behaviours that are absences. A field that parses and
 * does nothing is worse than one that is rejected, so it is written down.
 *
 * Revised on 2026-08-05 when tool calling shipped, which turned four of those
 * documented absences into behaviours and left the page saying the opposite of
 * the truth: `tools` and the sampling fields no longer parse and do nothing,
 * a `tool` role is no longer a 422, streaming can carry `usage`, and 422 now
 * carries the OpenAI envelope. A page describing what a feature *does not* do
 * is the kind that goes stale silently, so each of those is now stated with
 * the date it changed rather than simply rewritten.
 */
export function ApiReference() {
  const { data, isLoading, error, refetch } = useGatewayInfo();
  // The page an integrator reads while wiring a key into their own code, which
  // is where the capability convention is most often got wrong. The assistant
  // is told the same convention from the same live source this page renders.
  useAssistantSurface({ surface: 'api_docs' });

  const baseUrl = data?.base_url ?? 'https://<gateway>';
  const capabilities = data?.capabilities ?? [];
  const sample = capabilities[0] ?? 'chat';

  return (
    <div className="space-y-8">
      {/* An inline notice, not an early return. Only the origin and the
          capability badges come from the network; the header format, the
          capability convention, the request fields and the error table are the
          contract itself, and §4.4 traded `/openapi.json` away for them. They
          must not disappear because one call failed. */}
      {error ? (
        <div className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 p-4">
          <p className="text-sm">
            The live endpoint and capability list could not be loaded, so the
            origin below is a placeholder. Everything else on this page is
            accurate.
          </p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="text-sm underline"
          >
            Try again
          </button>
        </div>
      ) : null}

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">Endpoint</h2>
        <p className="text-sm text-muted-foreground">
          The API is OpenAI-compatible, so any client library that accepts a
          base URL works unchanged. Point it at:
        </p>
        <CodeBlock code={`${baseUrl}/v1`} label="Copy the base URL" />
        <p className="text-sm text-muted-foreground">
          Authenticate with the key as a bearer token. There is no other
          credential and no session.
        </p>
        <CodeBlock
          code={'Authorization: Bearer nx_live_<key id>.<secret>'}
          label="Copy the header"
        />
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          <code>model</code> names a capability, not a model
        </h2>
        <p className="text-sm text-muted-foreground">
          This is the one convention that differs from every other provider. A
          request asks for what it needs done and a routing policy decides which
          model on which node serves it, so models can be swapped, moved or
          upgraded without any client changing a line. The field keeps its
          OpenAI name so existing libraries work.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {isLoading ? (
            <span className="text-sm text-muted-foreground">
              Loading capabilities...
            </span>
          ) : capabilities.length ? (
            capabilities.map((capability) => (
              <Badge key={capability} variant="outline" className="font-mono">
                {capability}
              </Badge>
            ))
          ) : (
            <span className="text-sm text-muted-foreground">
              Nothing is routable yet. An administrator has to bind a routing
              policy to a registered model before any request can be served.
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          The same list is available on the wire as{' '}
          <code>GET /v1/models</code>, in OpenAI&apos;s shape, narrowed to what
          your key was issued for. A key is refused any capability it does not
          carry, so a key issued for <code>chat</code> cannot spend the
          hardware&apos;s time on anything else.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">A request</h2>
        <CodeBlock
          code={`curl ${baseUrl}/v1/chat/completions \\
  -H "Authorization: Bearer $NEXUS_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${sample}",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'`}
          label="Copy the request"
        />
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="font-mono text-muted-foreground">stream</dt>
          <dd>
            Server-sent events when true, terminated by{' '}
            <code>data: [DONE]</code>. Disconnecting cancels the generation
            rather than leaving it running.
          </dd>
          <dt className="font-mono text-muted-foreground">max_tokens</dt>
          <dd>
            Advisory. The platform applies its own ceiling regardless, and
            honours yours only where it is stricter. A cut generation reports{' '}
            <code>finish_reason: &quot;length&quot;</code>, never{' '}
            <code>stop</code>.
          </dd>
          <dt className="font-mono text-muted-foreground">think</dt>
          <dd>
            An extension, not part of the OpenAI schema. Omit to take the
            deployment default; <code>false</code> asks a deliberating model to
            answer directly. A model&apos;s reasoning comes back as{' '}
            <code>reasoning_content</code> and is deliberately never merged into{' '}
            <code>content</code> — echoing it back as history would feed the
            model its own scratch work.
          </dd>
          <dt className="font-mono text-muted-foreground">use_knowledge</dt>
          <dd>
            An extension. Retrieves from your tenant&apos;s knowledge base and
            grounds the answer on what comes back. Off by default, because
            grounding costs an embedding call and a slice of the context window,
            so it is asked for rather than assumed. See below for what it does
            and does not promise.
          </dd>
          <dt className="font-mono text-muted-foreground">
            knowledge_collection
          </dt>
          <dd>
            Restrict retrieval to one collection. Ignored unless{' '}
            <code>use_knowledge</code> is set. It can only narrow: the tenant
            scope is fixed by your key and no value here widens it.
          </dd>
        </dl>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="font-mono text-muted-foreground">
            temperature, top_p, seed, stop
          </dt>
          <dd>
            Honoured, and forwarded only when you set them, so the model&apos;s
            own defaults stay in force otherwise. <code>stop</code> takes a
            string or up to four of them. All four parsed and did nothing before
            2026-08-05.
          </dd>
          <dt className="font-mono text-muted-foreground">stream_options</dt>
          <dd>
            <code>{'{"include_usage": true}'}</code> adds a final frame carrying
            token counts before <code>[DONE]</code>. Off unless asked for,
            because that frame has an empty <code>choices</code> array and a
            client not expecting it may read it as malformed.
          </dd>
        </dl>
        <p className="text-sm text-muted-foreground">
          <strong>
            Everything else is accepted and silently ignored.
          </strong>{' '}
          The ones you might reasonably expect to work and which do nothing:{' '}
          <code>response_format</code>, <code>parallel_tool_calls</code>,{' '}
          <code>frequency_penalty</code> and <code>presence_penalty</code>. Two
          fields are refused rather than ignored, because serving them wrongly
          would be worse than saying no: <code>n</code> other than{' '}
          <code>1</code>, and a <code>tool_choice</code> of{' '}
          <code>required</code> or a named function.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Tool calling, and agent clients
        </h2>
        <p className="text-sm text-muted-foreground">
          Send <code>tools</code> and the model may answer with a call instead
          of prose. <strong>The platform never runs a tool.</strong> You execute
          it and send the result back as a message with role{' '}
          <code>tool</code>, quoting the <code>tool_call_id</code> from the call
          you are answering. That round trip is the whole mechanism, and it is
          what a coding agent such as Codex is doing on every turn.
        </p>
        <CodeBlock
          code={`{
  "model": "${sample}",
  "messages": [
    {"role": "user", "content": "what is in this directory"},
    {"role": "assistant", "content": null,
     "tool_calls": [{"id": "call_1", "type": "function",
                     "function": {"name": "sh", "arguments": "{\\"cmd\\":\\"ls\\"}"}}]},
    {"role": "tool", "tool_call_id": "call_1", "content": "a.txt b.txt"}
  ],
  "tools": [{"type": "function", "function": {
    "name": "sh", "description": "Run a shell command",
    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}
  }}]
}`}
          label="Copy the round trip"
        />
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="font-mono text-muted-foreground">finish_reason</dt>
          <dd>
            <code>tool_calls</code> when the model asked for one. Branch on it:
            it is how you tell &quot;run this and come back&quot; from an answer
            you should show someone.
          </dd>
          <dt className="font-mono text-muted-foreground">tool_call_id</dt>
          <dd>
            Generated by this platform, because the runtimes underneath do not
            all mint one. Send back exactly what you received; it is the only
            thing pairing your result with the request that caused it.
          </dd>
          <dt className="font-mono text-muted-foreground">arguments</dt>
          <dd>
            A JSON <em>string</em>, as OpenAI defines it, and passed through
            exactly as the model produced it.{' '}
            <strong>It is model output, so it can be malformed</strong> — parse
            defensively. A conversation containing one is still replayable: the
            platform will not reject on the way back in.
          </dd>
          <dt className="font-mono text-muted-foreground">tool_choice</dt>
          <dd>
            <code>auto</code> (the default) and <code>none</code> work.{' '}
            <code>required</code> and naming a function are refused with{' '}
            <code>400 runtime_capability_unsupported</code>: neither runtime
            here can force a call, and quietly giving you <code>auto</code>{' '}
            would answer a demand for a call with prose.
          </dd>
        </dl>
        <p className="text-sm text-muted-foreground">
          <strong>Tool definitions count towards the context limit</strong>, as
          does the call history you replay. A long agent conversation reaches
          the 413 below through accumulated tool output rather than through any
          single large message.
        </p>
        <p className="text-sm text-muted-foreground">
          Streaming delivers each call as one{' '}
          <code>delta.tool_calls</code> entry with a complete{' '}
          <code>arguments</code> string, rather than as the many fragments
          OpenAI sends. A client that concatenates fragments handles this
          correctly without changes — concatenating one piece is that piece —
          and the <code>index</code> field is present and runs across the whole
          stream, so a client buffering on it behaves as it would elsewhere.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>Ask an administrator to turn deliberation off</strong> for the
          capability you point an agent at. A thinking model reasons again on
          every tool round trip, which multiplies the cost of a task by the
          number of steps in it, and it is set per capability on the routing
          policy rather than per request.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Grounding on the knowledge base
        </h2>
        <p className="text-sm text-muted-foreground">
          With <code>use_knowledge: true</code> the platform embeds your latest
          question, retrieves passages from your tenant&apos;s documents, and
          puts them in front of the model as data. The frames themselves stay
          strictly OpenAI-shaped; which passages were used comes back as a
          response header, because an extra frame shape would be a protocol
          error to a client that parses the envelope strictly.
        </p>
        <CodeBlock
          code={'X-Knowledge-Sources: <document id>:<passage>,<document id>:<passage>'}
          label="Copy the header name"
        />
        <p className="text-sm text-muted-foreground">
          Ids and passage indexes only, never passage text — a header reaches
          access logs. The header is present on both the streaming and
          non-streaming paths, and is <strong>absent when nothing was
          retrieved</strong>.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>Retrieval usually degrades rather than failing.</strong> If
          the vector store is unreachable, or this deployment has no embedding
          model routed, or your question matched nothing, you get an ordinary
          ungrounded completion: 200, no header, no error. That is deliberate —
          an outage in an enhancement should not turn a working chat into a 503
          — and it means <code>use_knowledge: true</code> is a request rather
          than a guarantee. If your application depends on an answer being
          grounded, check for the header rather than assuming it.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>Two conditions are not survivable, and both fail the whole
          request rather than the retrieval.</strong> If the routed embedding
          model is missing from its runtime you get{' '}
          <code>404 model_not_found</code>, and if it sits on a runtime that
          cannot embed at all you get{' '}
          <code>400 runtime_capability_unsupported</code>. Neither can happen to
          the same request without <code>use_knowledge</code>, so dropping the
          flag is a workaround while an administrator fixes the{' '}
          <code>embedding</code> policy. Both are deployment faults; retrying
          identically will not clear either.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          What comes back
        </h2>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="font-mono text-muted-foreground">finish_reason</dt>
          <dd>
            <code>stop</code> means the model finished. <code>length</code>{' '}
            means the answer was cut, either at the token ceiling or at the
            platform&apos;s wall-clock deadline for a single generation — the
            two are not distinguishable from the response, and both mean the
            same thing to you: the reply is incomplete and continuing it is your
            decision. <code>tool_calls</code> means the model wants a tool run
            and is waiting for the result.
          </dd>
          <dt className="font-mono text-muted-foreground">usage</dt>
          <dd>
            All three figures are reported, and <code>total_tokens</code> is the
            sum of both sides. The quota on your key is spent by that same
            total, so a large prompt costs you whether or not the answer is
            long — on this hardware, reading the prompt is most of the work.
            <br />
            <strong>One exception worth knowing:</strong> if you disconnect
            before the response completes, <code>prompt_tokens</code> is
            recorded as <code>0</code> for that call. The runtime reports the
            figure only with its final chunk, so an abandoned request is
            under-counted rather than estimated.
          </dd>
          <dt className="font-mono text-muted-foreground">
            usage, when streaming
          </dt>
          <dd>
            Sent only if you ask, with{' '}
            <code>{'"stream_options": {"include_usage": true}'}</code>. The
            figures arrive in a frame of their own after the terminal one and
            before <code>[DONE]</code>, with an empty <code>choices</code>{' '}
            array. Without that option a streamed response carries no{' '}
            <code>usage</code> at all, which is how it behaved before
            2026-08-05. A stream that failed carries none either way: the counts
            would describe work that did not finish.
          </dd>
        </dl>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">Errors</h2>
        <p className="text-sm text-muted-foreground">
          Every failure the platform raises carries{' '}
          <code>
            {'{"error": {"type": "...", "code": "...", "message": "..."}}'}
          </code>
          . <code>type</code> is OpenAI&apos;s coarse classification, derived
          from the status; <code>code</code> is this platform&apos;s and is the
          one to branch on. Branch on it rather than on the status: 429, 403 and
          400 each cover two different conditions, and each pair needs different
          handling. One response does not carry this envelope: a 500, which is
          not JSON — see the last row of the table.
        </p>
        <h3 className="pt-2 font-heading text-sm font-semibold">
          A stream that fails after it has started
        </h3>
        <p className="text-sm text-muted-foreground">
          The table below describes failures that happen before any bytes are
          sent, which get a status code. Once the first frame is out the status
          line is already committed as 200 and cannot be taken back, so a
          failure mid-generation arrives in the body instead — a frame carrying{' '}
          <code>error.code</code> and <code>error.message</code>, and then{' '}
          <strong>
            the stream ends without <code>data: [DONE]</code>
          </strong>
          . Note that this frame carries no <code>type</code>: it is written by
          the stream itself rather than by the error response above, so{' '}
          <code>code</code> is the only field to branch on here.
        </p>
        <CodeBlock
          code={`data: {"error":{"code":"no_available_model","message":"..."}}

(stream ends; no [DONE])`}
          label="Copy the failure shape"
        />
        <p className="text-sm text-muted-foreground">
          This is inherent to server-sent events rather than a choice, and it
          makes <code>[DONE]</code> load-bearing:{' '}
          <strong>
            treat a stream that ended without it as a failed request
          </strong>
          , not as a short answer. A dropped connection ends the stream with
          neither a frame nor the sentinel, which the same rule covers. A
          truncated-but-successful answer is the opposite case and does reach{' '}
          <code>[DONE]</code>, reporting{' '}
          <code>finish_reason: &quot;length&quot;</code> first.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted-foreground">
              <tr className="border-b">
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 pr-4 font-medium">Code</th>
                <th className="py-2 font-medium">What to do</th>
              </tr>
            </thead>
            <tbody className="[&_td]:py-2 [&_td]:pr-4 [&_tr]:border-b">
              <tr>
                <td>400</td>
                <td className="font-mono text-xs">untrusted_proxy</td>
                <td>
                  The request did not arrive through this deployment&apos;s
                  front door, so no source address could be established. You
                  will see this if you reach the application port directly
                  rather than the published endpoint above. Nothing about the
                  key is wrong.
                </td>
              </tr>
              <tr>
                <td>400</td>
                <td className="font-mono text-xs">
                  runtime_capability_unsupported
                </td>
                <td>
                  Two conditions. A <code>tool_choice</code> of{' '}
                  <code>required</code> or a named function, which no runtime
                  here can enforce — send <code>auto</code> instead. Or, with{' '}
                  <code>use_knowledge</code>, an embedding model on a runtime
                  that cannot embed, in which case the request succeeds without
                  the flag and an administrator has to repoint the{' '}
                  <code>embedding</code> policy. Retrying identically helps in
                  neither case.
                </td>
              </tr>
              <tr>
                <td>401</td>
                <td className="font-mono text-xs">not_authenticated</td>
                <td>
                  Missing, malformed, unknown, expired or revoked key, or a
                  source the key&apos;s CIDR allowlist does not permit. All
                  answer identically on purpose — telling you which would tell
                  an attacker which to fix.
                </td>
              </tr>
              <tr>
                <td>403</td>
                <td className="font-mono text-xs">not_authorized</td>
                <td>
                  The key is valid but was not issued for the capability you
                  asked for. Reissue or edit the key; retrying will not help.
                </td>
              </tr>
              <tr>
                <td>403</td>
                <td className="font-mono text-xs">country_not_allowed</td>
                <td>
                  The request came from outside the countries this deployment
                  accepts. Nothing about the key is wrong, so reissuing it
                  changes nothing — this is the other 403, and the reason to
                  read the code rather than the status.
                </td>
              </tr>
              <tr>
                <td>404</td>
                <td className="font-mono text-xs">model_not_found</td>
                <td>
                  Routing picked a model that its runtime does not actually
                  have. A deployment fault rather than anything about your
                  request — the capability is configured but the weights behind
                  it are missing — so retrying the same call repeats it. Two
                  models can trigger it: the one serving your capability, and,
                  with <code>use_knowledge</code>, the one serving{' '}
                  <code>embedding</code>. In the second case the request
                  succeeds without the flag.
                </td>
              </tr>
              <tr>
                <td>422</td>
                <td className="font-mono text-xs">invalid_request</td>
                <td>
                  The request body did not match the schema, and{' '}
                  <code>message</code> names the field and the rule. A missing{' '}
                  <code>messages</code> array looks like this, as does a{' '}
                  <code>tool</code> message with no <code>tool_call_id</code>{' '}
                  and an image part in a <code>content</code> array. Before
                  2026-08-05 this was the framework&apos;s{' '}
                  <code>{'{"detail": [...]}'}</code>, which no OpenAI client
                  library could surface.
                </td>
              </tr>
              <tr>
                <td>429</td>
                <td className="font-mono text-xs">rate_limited</td>
                <td>
                  Requests per minute exceeded. <code>Retry-After</code> is
                  set; the window is short and retrying is the right response.
                </td>
              </tr>
              <tr>
                <td>429</td>
                <td className="font-mono text-xs">quota_exceeded</td>
                <td>
                  The daily token quota is spent. <code>Retry-After</code> is
                  set here too, but unlike the row above it is a fixed hour
                  rather than a measured wait — retrying inside the same day
                  cannot succeed, so back off until the quota resets rather than
                  looping.
                </td>
              </tr>
              <tr>
                <td>413</td>
                <td className="font-mono text-xs">context_too_long</td>
                <td>
                  The prompt exceeds the configured input ceiling. Shorten it;
                  the limit is about memory, not policy. Your tool definitions
                  and replayed tool calls are counted too, so an agent
                  conversation reaches this through accumulation rather than
                  through one large message.
                </td>
              </tr>
              <tr>
                <td>503</td>
                <td className="font-mono text-xs">no_available_model</td>
                <td>
                  Nothing can serve the capability right now: no routing policy
                  names it, or every candidate is offline, unloaded or busy.
                  The response deliberately does not say which. Retry with
                  backoff; if it persists, the deployment needs an
                  administrator. This is also the code a generation that dies
                  mid-stream carries, in the error frame described above.
                </td>
              </tr>
              <tr>
                <td>500</td>
                <td className="font-mono text-xs">—</td>
                <td>
                  <strong>The one response that is not JSON.</strong> Every
                  condition the platform anticipates is in a row above; a 500
                  means something it did not, so there is no code to give you
                  and the body is the framework&apos;s plain{' '}
                  <code>Internal Server Error</code>. Parse defensively — a
                  client that assumes an envelope on every non-2xx throws here,
                  on the one status where it most needs to degrade. Retry once;
                  if it repeats, an administrator needs the timestamp of your
                  request, because the detail went to the log rather than to
                  you.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">Limits</h2>
        <p className="text-sm text-muted-foreground">
          Each key carries its own requests-per-minute limit and daily token
          quota, and optionally a list of source addresses it may be used from.
          They are visible on the{' '}
          <Link href="/api-keys" className="underline">
            API keys
          </Link>{' '}
          page. The source allowlist is the one control that survives the key
          leaking, so set it wherever the caller has a fixed address.
        </p>
        <p className="text-sm text-muted-foreground">
          Every key expires, with no option not to. Expiry is what forces
          rotation; extend it from the same page before it lapses, which does
          not change the secret and needs no redeployment.
        </p>
      </section>
    </div>
  );
}
