import { CodeBlock } from '@/components/composed/code-block';
export function ErrorsSection() {
  return (
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
          </strong>
          , and every error body repeats it as <code>error.request_id</code>.
          The detail behind an error is never included in the response; it is
          written to the platform&apos;s log, keyed by this identifier. When
          reporting a failure, <strong>quote the identifier</strong>: it is the
          difference between an administrator searching timestamps and locating
          the exact entry. While an integration is being debugged, an
          administrator can open a time-boxed <em>debug window</em> on the key,
          from the API keys page, during which error responses carry that detail
          directly as <code>error.detail</code>.
        </p>
        <h3 className="pt-2 font-heading text-sm font-semibold">
          A stream that fails after it has started
        </h3>
        <p className="text-sm text-muted-foreground">
          The table below describes failures that happen before any bytes are
          sent, which receive a status code. Once the first frame has been
          sent, the status line is committed as 200 and cannot be withdrawn, so
          a failure mid-generation arrives in the body instead: a frame carrying{' '}
          <code>error.code</code> and <code>error.message</code>, and then{' '}
          <strong>
            the stream ends without <code>data: [DONE]</code>
          </strong>
          . This frame carries no <code>type</code>: it is written by
          the stream itself rather than by the error response above, so{' '}
          <code>code</code> is the only field to branch on here.
        </p>
        <CodeBlock
          code={`data: {"error":{"code":"stream_interrupted","message":"...","request_id":"req_..."}}

(stream ends; no [DONE])`}
          label="Copy the failure shape"
        />
        <p className="text-sm text-muted-foreground">
          This is inherent to server-sent events rather than a design decision,
          and it makes <code>[DONE]</code> load-bearing:{' '}
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
                  front door, so no source address could be established. It
                  occurs where the application port is reached directly rather
                  than the published endpoint above. Nothing about the key is at
                  fault.
                </td>
              </tr>
              <tr>
                <td>400</td>
                <td className="font-mono text-xs">
                  runtime_capability_unsupported
                </td>
                <td>
                  Three conditions, none of them resolved by an identical
                  retry. A <code>tool_choice</code> of <code>required</code> or
                  of a named function, which no runtime here can enforce: send{' '}
                  <code>auto</code>. A replayed assistant turn whose tool-call{' '}
                  <code>arguments</code> do not parse as JSON, on a runtime that
                  takes arguments as an object, as Ollama does: repair or discard
                  that turn. Or, with <code>use_knowledge</code>, an embedding
                  model on a runtime that cannot embed, in which case the request
                  succeeds without the flag and an administrator must repoint the{' '}
                  <code>embedding</code> policy.
                </td>
              </tr>
              <tr>
                <td>401</td>
                <td className="font-mono text-xs">not_authenticated</td>
                <td>
                  Missing, malformed, unknown, expired or revoked key, or a
                  source the key&apos;s CIDR allowlist does not permit. All
                  return the same response by design: naming the condition would
                  tell an attacker which one to address.
                </td>
              </tr>
              <tr>
                <td>403</td>
                <td className="font-mono text-xs">capability_not_issued</td>
                <td>
                  The <code>model</code> field named something this key may not
                  call, most often a client&apos;s own default model name
                  rather than a capability. The message names what was requested
                  and what may be requested instead; <code>GET /v1/models</code>{" "}
                  returns the same list. Both are also available as fields —{' '}
                  <code>capability</code> and <code>available</code> — so a
                  client can branch on them rather than parse a sentence.
                  Retrying does not succeed. A key may be issued with a default
                  capability, which serves one of the key&apos;s own instead of
                  refusing; the response then carries{' '}
                  <code>X-Capability-Defaulted</code> naming what ran.
                </td>
              </tr>
              <tr>
                <td>403</td>
                <td className="font-mono text-xs">not_authorized</td>
                <td>
                  The key may not perform this action at all: it holds none of
                  the scopes the endpoint requires. Distinct from the row above,
                  which concerns <em>which</em> capability was requested. This
                  condition is not corrected by changing the <code>model</code>{' '}
                  field.
                </td>
              </tr>
              <tr>
                <td>403</td>
                <td className="font-mono text-xs">country_not_allowed</td>
                <td>
                  The request came from outside the countries this deployment
                  accepts. Nothing about the key is at fault, so reissuing it
                  has no effect. This is the second condition returning 403, and
                  the reason to read the code rather than the status.
                </td>
              </tr>
              <tr>
                <td>404</td>
                <td className="font-mono text-xs">model_not_found</td>
                <td>
                  Routing selected a model that its runtime does not hold. This
                  is a deployment fault rather than a property of the request —
                  the capability is configured but the weights behind it are
                  absent — so an identical retry reproduces it. Two models can
                  produce it: the one serving the requested capability and, with{' '}
                  <code>use_knowledge</code>, the one serving{' '}
                  <code>embedding</code>. In the second case the request succeeds
                  without the flag.
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
                  and an image part in a <code>content</code> array.
                </td>
              </tr>
              <tr>
                <td>429</td>
                <td className="font-mono text-xs">rate_limited</td>
                <td>
                  Requests per minute exceeded. <code>Retry-After</code> is
                  set; the window is short and retrying is the correct
                  response. The same figure appears in the body as{' '}
                  <code>retry_after_seconds</code>, for clients that read bodies
                  rather than headers.
                </td>
              </tr>
              <tr>
                <td>429</td>
                <td className="font-mono text-xs">quota_exceeded</td>
                <td>
                  The key&apos;s token budget is spent. Carries{' '}
                  <code>type: &quot;insufficient_quota&quot;</code>, not{' '}
                  <code>rate_limit_error</code>, since retrying cannot succeed
                  and an OpenAI client library branching on <code>type</code>{' '}
                  stops rather than exhausting its backoff.{' '}
                  <code>Retry-After</code> is a computed wait, described below;
                  it is frequently many hours, and should be treated as a stop
                  rather than as a delay. It appears in the body as{' '}
                  <code>retry_after_seconds</code>, and is omitted from both
                  rather than estimated where the recovery time cannot be
                  projected.
                </td>
              </tr>
              <tr>
                <td>413</td>
                <td className="font-mono text-xs">context_too_long</td>
                <td>
                  The prompt exceeds the configured input ceiling. Shorten it;
                  the limit is a memory constraint rather than a policy, and an
                  unchanged retry cannot succeed. The ceiling is{' '}
                  <strong>at most 122,880 tokens</strong> across everything the
                  model will read, tool definitions and replayed tool calls
                  included, so an agent conversation reaches this through
                  accumulation rather than through one large message. It is lower
                  where a smaller model is serving the capability, which is why
                  the response states the figure it was judged against rather
                  than leaving the maximum to be assumed.
                  <br />
                  It carries its own arithmetic: <code>estimated</code> and <code>limit</code> as
                  numbers, <code>composition</code>, which splits the figure
                  across messages, prior tool calls and tool definitions and
                  names the largest single message&apos;s share, and{' '}
                  <code>basis</code>, which states how the figure was arrived
                  at. The three shares have different remedies: an accumulated
                  conversation is addressed by starting a new one, a single very
                  large message by not reading that file in, and dominant tool
                  definitions by reducing the client&apos;s tool list, which
                  starting a new conversation does not affect. The same figures
                  are repeated in <code>message</code> for clients that print
                  only that field.
                  <br />
                  <code>basis</code> is one of three values and they are not
                  interchangeable. <code>tokenizer</code> means the prompt was
                  counted with the vocabulary and chat template of the model that
                  would have read it, including the framing the runtime applies
                  to each turn. It is the figure that model would have charged,
                  and can be budgeted against directly.{' '}
                  <code>estimate</code> means no vocabulary was available for
                  that model and the figure was inferred from character widths.
                  It runs roughly 20% to 60% above the true count on prose,
                  source and tool schemas — the ratio is a property of the sample
                  rather than a constant of the content type — and can run well
                  below it on dense identifiers such as UUIDs or base64. Treat it
                  as an upper bound on ordinary content and as no bound at all on
                  the rest.{' '}
                  <code>lower_bound</code> means the request was turned away
                  before a model had been selected, on a bound that no
                  tokenizer could bring under the ceiling. The true figure is
                  above the number shown, and a payload producing this basis is
                  in the order of a megabyte of text.
                  <br />
                  <strong>
                    Every refusal is stored, and the account the key belongs to
                    can read its own without an administrator.
                  </strong>{' '}
                  The code, the status, the message and these figures are
                  retained against the <code>request_id</code> in the body for
                  this deployment&apos;s refusal retention window — thirty days
                  unless an administrator has changed it, and it may be set
                  between 7 and 180 days — so a client that discards the response
                  still leaves a record more useful than a container log. Nothing
                  about the request itself is stored: no messages, no tool
                  definitions, no model name.
                </td>
              </tr>
              <tr>
                <td>413</td>
                <td className="font-mono text-xs">request_too_large</td>
                <td>
                  The request body itself is over the platform&apos;s byte
                  ceiling, which is a separate limit from the row above and is
                  measured differently. That limit counts tokens in what the
                  model will read and is applied after the request is parsed and
                  the key is checked; this one counts raw bytes and is applied
                  before either, so it is the only error here that can be
                  received without a valid key. In practice it is reached only by
                  sending something far larger than the context ceiling would
                  permit in any case: a whole file pasted into a message, or a
                  body other than the one intended.
                </td>
              </tr>
              <tr>
                <td>503</td>
                <td className="font-mono text-xs">no_available_model</td>
                <td>
                  The routing layer found nothing to send the request to: no
                  policy names the capability, every candidate is offline or
                  unloaded, or the runtime process refused the connection. The
                  response does not distinguish between them. Retry with
                  backoff; where the condition persists, the deployment requires
                  an administrator. The two rows below are distinct codes with
                  different remedies, and an integration branching on this one
                  alone should be updated to recognise them.
                </td>
              </tr>
              <tr>
                <td>503</td>
                <td className="font-mono text-xs">runtime_timeout</td>
                <td>
                  The runtime took longer than the platform&apos;s read timeout
                  before producing its first byte, almost always prompt
                  evaluation on a large context.{' '}
                  <strong>
                    An unchanged retry is unlikely to succeed; send less.
                  </strong>{' '}
                  A cancelled prefill is discarded rather than retained.
                  Measured on this deployment by aborting a cold prefill part
                  way, the retry re-evaluated 20,919 tokens in 33.5 seconds, the
                  full cold rate, having retained nothing. The prefix cache does
                  make an agent&apos;s <em>next</em> turn nearly free, but it
                  never holds a prompt whose evaluation was interrupted, which is
                  the only condition under which this code is returned.
                </td>
              </tr>
              <tr>
                <td>503</td>
                <td className="font-mono text-xs">overloaded</td>
                <td>
                  Every inference slot was busy for the duration of the queue
                  wait, which is two minutes. The deployment is healthy and at
                  capacity. <code>Retry-After</code> is set, and backing off for
                  that interval is the correct response. It is distinct from
                  <code>no_available_model</code>, which reports a
                  deployment that cannot serve the request at all.
                </td>
              </tr>
              <tr>
                <td>—</td>
                <td className="font-mono text-xs">stream_interrupted</td>
                <td>
                  Returned only in the mid-stream error frame above, or, rarely,
                  as a 503 where the runtime&apos;s stream ended before producing
                  anything: the generation stalled, or its stream ended without a
                  terminal event. A partial answer may have been received.
                  Whether to retry is a question of the caller&apos;s
                  idempotence, since the platform has no knowledge of what
                  already-executed tool calls have done.
                </td>
              </tr>
              <tr>
                <td>500</td>
                <td className="font-mono text-xs">internal_error</td>
                <td>
                  A condition the platform did not anticipate. It carries the
                  same envelope as every other error. The traceback is written to
                  the log; the response carries <code>error.request_id</code>,
                  and quoting that identifier is how an administrator locates the
                  traceback. Retry once; where it recurs, report the
                  identifier.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
  );
}
