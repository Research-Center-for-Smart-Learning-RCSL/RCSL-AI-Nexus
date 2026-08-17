'use client';

import Link from 'next/link';

import { useRef } from 'react';

import { Badge } from '@/components/ui/badge';
import { CodeBlock } from '@/components/composed/code-block';
import { ExportMarkdown } from '@/components/composed/export-markdown';
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
 *
 * Revised on 2026-08-05 for the error-precision work: every response now
 * carries `X-Request-Id` (repeated as `error.request_id`), the 500 gained an
 * envelope, `no_available_model` split into three codes whose remedies
 * differ, the slot queue refuses with `overloaded` instead of hanging, and a
 * per-key debug window can put `error.detail` in responses for a bounded
 * time. The same revision added the sections integrators had to learn by
 * surprise: client timeout sizing and the `extra_body` route to the
 * platform's extension fields.
 *
 * Revised on 2026-08-17 for three things this page said that had stopped being
 * true. The timeout section still described the 600-second read timeout and a
 * prompt-evaluation rate measured before the context raise of 2026-08-14, so
 * it advertised a 25-minute worst case and a 1600-second client timeout
 * against a deployment whose real bounds are 1200 + 900 seconds. The
 * `prompt_template` request field was missing entirely, on a page whose own
 * introduction promises every field a request accepts. And "two fields are
 * refused" was followed by a list of four.
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
  // As on the agent-setup page: generated from what is rendered, so the origin
  // and capability list in the export are this deployment's own.
  const content = useRef<HTMLDivElement>(null);

  return (
    <div className="space-y-8">
      <div className="flex justify-end" data-md-skip>
        <ExportMarkdown
          contentRef={content}
          title="API reference"
          filename="rcsl-ai-nexus-api-reference"
        />
      </div>
      <div ref={content} className="space-y-8">
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
        <CodeBlock
          code={`{
  "object": "list",
  "data": [
    {"id": "${sample}", "object": "model", "created": 0, "owned_by": "rcsl"}
  ]
}`}
          label="Copy the /v1/models shape"
        />
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
          <dt className="font-mono text-muted-foreground">prompt_template</dt>
          <dd>
            An extension. Names one of your tenant&apos;s saved prompt
            templates, whose text is placed at the front of the conversation,
            ahead of any system message you send, which is kept rather than
            replaced. There is no substitution: a template is fixed text, and
            what you choose is which one rather than what it says. A name that
            does not resolve is a <code>404</code>, so a request never quietly
            runs without the template it asked for.
          </dd>
        </dl>
        <p className="text-sm text-muted-foreground">
          <strong>
            <code>think</code>, <code>use_knowledge</code>,{' '}
            <code>knowledge_collection</code> and{' '}
            <code>prompt_template</code> are not OpenAI schema fields
          </strong>
          , and the official SDKs refuse unknown named arguments rather than
          forwarding them. Send them through the SDK&apos;s escape hatch — in
          Python, <code>extra_body</code>:
        </p>
        <CodeBlock
          code={`client.chat.completions.create(
    model="${sample}",
    messages=[{"role": "user", "content": "..."}],
    extra_body={"think": False, "use_knowledge": True},
)`}
          label="Copy the extra_body example"
        />
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
          <code>frequency_penalty</code> and <code>presence_penalty</code>.
          Four requests are refused rather than ignored, because serving them
          wrongly would be worse than refusing: <code>n</code> other than{' '}
          <code>1</code>, a <code>tool_choice</code> of <code>required</code>{' '}
          or a named function, the deprecated <code>functions</code> /{' '}
          <code>function_call</code> spellings (send <code>tools</code> and{' '}
          <code>tool_choice</code>; before 2026-08-05 these were silently
          ignored, which stalled older client libraries exactly the way a
          dropped <code>tools</code> once did), and{' '}
          <code>stream_options</code> on a request whose <code>stream</code> is
          not <code>true</code>.
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
            defensively. Replaying a turn whose arguments do not parse is
            refused with <code>400 runtime_capability_unsupported</code> when
            the serving runtime takes arguments as an object, as Ollama does
            (measured 2026-08-05; this page said the opposite before that
            date). Repair or drop that turn — retrying replays the failure.
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
          Two wire protocols, and which one your client speaks
        </h2>
        <p className="text-sm text-muted-foreground">
          Everything above describes{' '}
          <code>POST /v1/chat/completions</code>, which is the documented
          interface and unchanged. Since 2026-08-07 the gateway also serves{' '}
          <code>POST /v1/responses</code>, OpenAI&apos;s newer Responses API,
          because some clients no longer speak the older one.{' '}
          <strong>
            Both route through the same policy, the same key checks and the same
            limits
          </strong>{' '}
          — only the shape on the wire differs, so the capability you ask for
          and the model that serves it are identical either way.
        </p>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="font-mono text-muted-foreground">Codex</dt>
          <dd>
            Needs <code>/v1/responses</code>. It removed Chat Completions
            support in February 2026, so <code>wire_api = &quot;responses&quot;</code>{' '}
            is required in <code>~/.codex/config.toml</code> and{' '}
            <code>wire_api = &quot;chat&quot;</code> refuses to start.
          </dd>
          <dt className="font-mono text-muted-foreground">
            Most libraries
          </dt>
          <dd>
            The OpenAI SDKs, LangChain, Cline, Continue and anything taking a
            base URL use <code>/v1/chat/completions</code>. Nothing to change.
          </dd>
          <dt className="font-mono text-muted-foreground">Claude Code</dt>
          <dd>
            <strong>Cannot connect to this gateway.</strong> It speaks
            Anthropic&apos;s Messages API (<code>/v1/messages</code>), which the
            platform does not serve. A translating proxy in front is the only
            route today.
          </dd>
        </dl>
        <p className="text-sm text-muted-foreground">
          The Responses API carries tools <em>flat</em> —{' '}
          <code>
            {'{"type": "function", "name": ..., "parameters": ...}'}
          </code>{' '}
          — where Chat Completions nests them under a{' '}
          <code>function</code> key, and its system prompt arrives as a
          top-level <code>instructions</code> string rather than as a message.
          The platform translates both onto the same request, so this only
          matters if you are writing the client yourself.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>Server-side tools are not served.</strong> A{' '}
          <code>web_search</code> tool is refused with{' '}
          <code>400 runtime_capability_unsupported</code> when the client
          actually enables it — performing one would mean this gateway making
          outbound web requests, which it deliberately cannot do. A disabled
          one, and any tool type this platform does not recognise, is dropped
          instead and named in the <code>X-Dropped-Tools</code> response header,
          so a capability the model never saw is findable rather than a mystery.
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
          One measured limit of the models, not of the API
        </h2>
        <p className="text-sm text-muted-foreground">
          <strong>
            A model here will answer a question its input cannot answer.
          </strong>{' '}
          Measured on this deployment on 2026-08-15, against a task whose data
          does not determine the result: every model tested returned a confident
          figure rather than reporting the gap — nine samples out of nine, with
          the working shown. It is a property of the models rather than of this
          platform, so it is not addressed by choosing a different capability,
          by <code>use_knowledge</code>, or by any field in this document.
        </p>
        <p className="text-sm text-muted-foreground">
          It is here because it has a bearing on how you write a client. An
          application that shows a model&apos;s answer to a person can note
          where it came from; one that parses a number out of it and acts on it
          has no signal to branch on, because a fabricated answer is
          well-formed, arrives with <code>finish_reason: &quot;stop&quot;</code>{' '}
          and looks exactly like a correct one. Where a wrong answer costs
          something, have the model produce the inputs and do the arithmetic
          yourself.
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
        <p className="text-sm text-muted-foreground">
          <strong>The full frame sequence of one streamed answer</strong>, with
          every optional frame present. Each is an ordinary OpenAI chunk;
          what varies is which key the delta carries. Order is contractual —
          in particular <code>tool_calls</code> always precedes the terminal
          frame, because a client that has seen <code>finish_reason</code> has
          stopped reading deltas:
        </p>
        <CodeBlock
          code={`data: {"choices":[{"delta":{"role":"assistant"}, ...}]}          <- always first
data: {"choices":[{"delta":{"reasoning_content":"..."}, ...}]} <- thinking models only, repeats
data: {"choices":[{"delta":{"content":"..."}, ...}]}           <- repeats per token
data: {"choices":[{"delta":{"tool_calls":[...]}, ...}]}        <- only when the model calls
data: {"choices":[{"delta":{}, "finish_reason":"stop"}]}       <- terminal frame
data: {"choices":[], "usage":{...}}                            <- only with include_usage
data: [DONE]`}
          label="Copy the frame sequence"
        />
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Timeouts, and sizing your client&apos;s
        </h2>
        <p className="text-sm text-muted-foreground">
          <strong>
            The first token of a large request can legitimately take close to
            twenty minutes to arrive.
          </strong>{' '}
          Prompt evaluation produces no bytes while it runs, so a conversation
          near the context ceiling is minutes of silence before anything
          streams — that silence is work, not failure. Two bounds apply in
          sequence, and they compose: the platform allows up to 20 minutes
          between bytes from the runtime, which is what bounds reading the
          prompt, and up to 15 minutes of wall clock for writing the answer,
          counted from the first chunk. One request&apos;s worst case, end to
          end, is therefore <strong>35 minutes</strong>.
        </p>
        <p className="text-sm text-muted-foreground">
          Most SDK defaults are shorter than that. The OpenAI Python
          SDK&apos;s default overall timeout is 600 seconds, so on a long
          agent conversation <em>your own client</em> gives up first, and the
          resulting connection error is indistinguishable from a platform
          failure. Set the client&apos;s timeout to at least 2100 seconds for
          agent workloads:
        </p>
        <CodeBlock
          code={`client = OpenAI(base_url="${baseUrl}/v1", api_key=key, timeout=2100.0)`}
          label="Copy the timeout example"
        />
        <p className="text-sm text-muted-foreground">
          Two more waits are bounded and report themselves: a request that
          arrives with every inference slot busy queues for at most two
          minutes and is then refused as <code>503 overloaded</code> with{' '}
          <code>Retry-After</code> (before 2026-08-05 it queued without limit,
          in silence), and a runtime that takes longer than the platform&apos;s
          own read timeout returns <code>503 runtime_timeout</code> — see the
          table below for why that one is worth retrying immediately.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">Errors</h2>
        <p className="text-sm text-muted-foreground">
          Every failure the platform raises carries{' '}
          <code>
            {'{"error": {"type": "...", "code": "...", "message": "..."}}'}
          </code>
          . <code>type</code> is OpenAI&apos;s coarse classification, usually
          derived from the status; <code>code</code> is this platform&apos;s and
          is the more precise of the two. Branch on one of them rather than on
          the status: 429, 403 and 400 each cover two different conditions, and
          each needs different handling. Where the status would classify two
          remedies alike, <code>type</code> is set from the condition instead —
          a spent quota is <code>insufficient_quota</code> rather than the{' '}
          <code>rate_limit_error</code> its 429 would otherwise imply.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>
            Every response carries <code>X-Request-Id</code>
          </strong>{' '}
          (since 2026-08-05), and every error body repeats it as{' '}
          <code>error.request_id</code>. The detail behind an error is
          deliberately never in the response — it goes to the platform&apos;s
          log, keyed by this id — so when you report a failure,{' '}
          <strong>quote the id</strong>: it is the difference between an
          administrator grepping timestamps and finding the exact line. If you
          are actively debugging an integration, an administrator can open a
          time-boxed <em>debug window</em> on your key (API keys page), during
          which error responses carry that detail directly as{' '}
          <code>error.detail</code>.
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
          code={`data: {"error":{"code":"stream_interrupted","message":"...","request_id":"req_..."}}

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
                  Three conditions, none helped by an identical retry. A{' '}
                  <code>tool_choice</code> of <code>required</code> or a named
                  function, which no runtime here can enforce — send{' '}
                  <code>auto</code>. A replayed assistant turn whose tool-call{' '}
                  <code>arguments</code> do not parse as JSON, on a runtime
                  that takes arguments as an object (Ollama does) — repair or
                  drop that turn. Or, with <code>use_knowledge</code>, an
                  embedding model on a runtime that cannot embed, in which case
                  the request succeeds without the flag and an administrator
                  has to repoint the <code>embedding</code> policy.
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
                <td className="font-mono text-xs">capability_not_issued</td>
                <td>
                  The <code>model</code> field named something this key may not
                  call — most often a client&apos;s own default model name
                  rather than a capability. The message names what you asked for
                  and what you may ask for instead; <code>GET /v1/models</code>{" "}
                  is the same list. Retrying will not help.
                </td>
              </tr>
              <tr>
                <td>403</td>
                <td className="font-mono text-xs">not_authorized</td>
                <td>
                  The key may not perform this action at all — it holds none of
                  the scopes the endpoint requires. Distinct from the row above,
                  which is about <em>which</em> capability was asked for; this
                  one is not fixed by changing the <code>model</code> field.
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
                  The key&apos;s token budget is spent. Carries{' '}
                  <code>type: &quot;insufficient_quota&quot;</code>, not{' '}
                  <code>rate_limit_error</code> — retrying cannot succeed, and
                  an OpenAI client library branching on <code>type</code> will
                  stop rather than exhaust its backoff. <code>Retry-After</code>{' '}
                  is a measured wait (see below); it is often many hours, so
                  treat it as a stop rather than a sleep.
                </td>
              </tr>
              <tr>
                <td>413</td>
                <td className="font-mono text-xs">context_too_long</td>
                <td>
                  The prompt exceeds the configured input ceiling. Shorten it;
                  the limit is about memory, not policy, and retrying unchanged
                  cannot succeed. To budget for it yourself: the ceiling is{' '}
                  <strong>98,304 tokens</strong> over everything the model will
                  read — your tool definitions and replayed tool calls included
                  — so an agent conversation reaches this through accumulation
                  rather than through one large message.
                  <br />
                  Tokens are estimated from the text, weighting characters
                  outside ASCII far more heavily, because they cost far more:
                  measured on this deployment, English prose runs about 4.6
                  characters per token and Traditional Chinese about 1.4. A
                  conversation in Chinese therefore reaches the ceiling in
                  roughly a third of the characters an English one does. Until
                  2026-08-14 a flat four-per-token rule applied to both, which
                  admitted CJK conversations well past the stated limit.
                </td>
              </tr>
              <tr>
                <td>413</td>
                <td className="font-mono text-xs">request_too_large</td>
                <td>
                  The request body itself is over the platform&apos;s byte
                  ceiling, which is a separate limit from the row above and
                  measured differently. That one counts tokens in what the model
                  will read and is applied after your request is parsed and your
                  key is checked; this one counts raw bytes and is applied
                  before either, so it is the one error here you can receive
                  without a valid key. In practice you reach it only by sending
                  something far larger than the context ceiling would allow
                  anyway &mdash; a whole file pasted into a message, or a body
                  that is not what you meant to send.
                </td>
              </tr>
              <tr>
                <td>503</td>
                <td className="font-mono text-xs">no_available_model</td>
                <td>
                  The routing layer found nothing to send the request to: no
                  policy names the capability, every candidate is offline or
                  unloaded, or the runtime process refused the connection. The
                  response deliberately does not say which. Retry with backoff;
                  if it persists, the deployment needs an administrator. Until
                  2026-08-05 this code also covered the two rows below, whose
                  remedies are different — an older integration branching on it
                  should learn the new codes.
                </td>
              </tr>
              <tr>
                <td>503</td>
                <td className="font-mono text-xs">runtime_timeout</td>
                <td>
                  The runtime took longer than the platform&apos;s read timeout
                  before producing its first byte — almost always prompt
                  evaluation on a large context.{' '}
                  <strong>Retry immediately, once:</strong> the prompt is now
                  in the runtime&apos;s prefix cache, so the evaluation that
                  just timed out is nearly free the second time. This is the
                  one 503 where an instant retry is the measured, correct
                  response.
                </td>
              </tr>
              <tr>
                <td>503</td>
                <td className="font-mono text-xs">overloaded</td>
                <td>
                  Every inference slot was busy for the whole queue wait (two
                  minutes). The deployment is healthy, just full —{' '}
                  <code>Retry-After</code> is set, and backing off for it is
                  the right response. Distinct from{' '}
                  <code>no_available_model</code> on purpose: busy and broken
                  used to be indistinguishable.
                </td>
              </tr>
              <tr>
                <td>—</td>
                <td className="font-mono text-xs">stream_interrupted</td>
                <td>
                  Only ever seen in the mid-stream error frame above (or, rarely,
                  as a 503 when the runtime&apos;s stream ended before producing
                  anything): the generation stalled or its stream ended without
                  a terminal event. You may hold a partial answer. Whether to
                  retry is your idempotence judgement — nothing here knows what
                  your tool calls already did.
                </td>
              </tr>
              <tr>
                <td>500</td>
                <td className="font-mono text-xs">internal_error</td>
                <td>
                  Something the platform did not anticipate. Since 2026-08-05
                  this carries the same envelope as every other error —
                  before that it was the framework&apos;s bare{' '}
                  <code>Internal Server Error</code> text, the one non-JSON
                  body the API could produce. The traceback went to the log;
                  what you get is <code>error.request_id</code>, and quoting it
                  is exactly how an administrator finds that traceback. Retry
                  once; if it repeats, report the id.
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
        <p className="text-sm text-muted-foreground">
          <strong>
            There are no <code>x-ratelimit-*</code> response headers.
          </strong>{' '}
          OpenAI sends remaining-quota headers on every response and some
          client libraries read them; here the only signals are{' '}
          <code>429 rate_limited</code> / <code>quota_exceeded</code> when a
          limit is reached, each with <code>Retry-After</code>. A client that
          paces itself from the headers will simply not pace itself — listed
          rather than left to be discovered.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>The token quota is a rolling 24 hours, not a calendar day.</strong>{' '}
          Nothing resets at midnight, and an exhausted key does not come back
          all at once: each past request stops counting 24 hours after it was
          made, so the budget returns in the pieces it was spent in. The{' '}
          <code>Retry-After</code> on <code>quota_exceeded</code> is the
          projected moment enough of that spend has aged out, and the message
          states the same wait in round hours.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>
            An exhausted quota does not stop <code>GET /v1/models</code>.
          </strong>{' '}
          It runs no model, so there is nothing for a token budget to charge,
          and every OpenAI-compatible client lists models before it can send
          anything. Gating it made a spent quota look like a broken connection.
          Every other check still applies to that call.
        </p>
      </section>
      </div>
    </div>
  );
}
