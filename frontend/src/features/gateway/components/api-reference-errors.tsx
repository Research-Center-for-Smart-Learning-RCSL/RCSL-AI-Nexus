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
                  is the same list, and since 2026-08-18 the two are fields as
                  well as prose — <code>capability</code> and{' '}
                  <code>available</code> — so a client can branch on them
                  instead of parsing a sentence. Retrying will not help. A key
                  can be issued with a default capability, which serves one of
                  its own instead of refusing; the response then carries{' '}
                  <code>X-Capability-Defaulted</code> naming what actually ran.
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
                  The same figure is in the body as{' '}
                  <code>retry_after_seconds</code>, for a client that reads
                  bodies and not headers.
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
                  treat it as a stop rather than a sleep. It is in the body too,
                  as <code>retry_after_seconds</code>, and omitted from both
                  rather than guessed at when the recovery time cannot be
                  projected.
                </td>
              </tr>
              <tr>
                <td>413</td>
                <td className="font-mono text-xs">context_too_long</td>
                <td>
                  The prompt exceeds the configured input ceiling. Shorten it;
                  the limit is about memory, not policy, and retrying unchanged
                  cannot succeed. To budget for it yourself: the ceiling is{' '}
                  <strong>at most 122,880 tokens</strong> over everything the
                  model will read — your tool definitions and replayed tool
                  calls included — so an agent conversation reaches this through
                  accumulation rather than through one large message. It is
                  lower when a smaller model is serving your capability, which
                  is why the response states the figure it judged against rather
                  than leaving you to assume the maximum.
                  <br />
                  It carries its own arithmetic: <code>estimated</code> and <code>limit</code> as
                  numbers, <code>composition</code>, which splits the figure
                  across messages, prior tool calls and tool definitions and
                  names the largest single message&apos;s share, and{' '}
                  <code>basis</code>, which says how the figure was arrived at.
                  The three shares have different remedies — a conversation that
                  grew is fixed by starting a new one, one enormous message by
                  not reading that file in, and tool definitions that dominate by
                  trimming the client&apos;s tool list, which starting a new
                  conversation does nothing about. The same figures are repeated
                  in <code>message</code> for clients that print only that.
                  <br />
                  <code>basis</code> is one of three values and they are not
                  interchangeable. <code>tokenizer</code> means the prompt was
                  counted with the vocabulary and chat template of the model that
                  would have read it, including the framing the runtime wraps
                  each turn in; it is the figure that model would have charged,
                  and you can budget against it directly.{' '}
                  <code>estimate</code> means no vocabulary was available for
                  that model and the figure was inferred from character widths,
                  which runs roughly 20% to 60% above the real count on prose,
                  source and tool schemas — the ratio is a property of the
                  sample rather than a constant of the content type — and can
                  run well below it on dense identifiers
                  such as uuids or base64 — so treat it as an upper bound on
                  ordinary content and nothing at all on the rest.{' '}
                  <code>lower_bound</code> means the request was turned away
                  before a model had been chosen, on a bound no tokenizer could
                  bring under the ceiling; the true figure is above the number
                  shown, and a payload that provokes this one is around a
                  megabyte of text.
                  <br />
                  Before 2026-08-17 every refusal here was an{' '}
                  <code>estimate</code>, and one of them was wrong by enough to
                  matter: a client was refused at 140,059 estimated tokens on a
                  payload of about 99,000 real ones, which the model serving it
                  could have read. That is why the field exists rather than
                  being left to be inferred.
                  <br />
                  <strong>
                    Every refusal is stored, and the account the key belongs to
                    can read its own back without an administrator.
                  </strong>{' '}
                  Since 2026-08-18 the code, the status, the message and these
                  figures are kept against the <code>request_id</code> in the
                  body for this deployment&apos;s refusal retention window —
                  thirty days unless an administrator has moved it, and it may
                  be set anywhere from 7 to 180 days — so a client that
                  swallows the response leaves an operator something better to
                  read than a container log. Nothing about your request is
                  stored: no messages, no tool definitions, no model name.
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
                  <strong>
                    Retrying the same request unchanged is unlikely to help;
                    send less.
                  </strong>{' '}
                  A prefill that is cancelled is discarded rather than kept:
                  measured on 2026-08-14 by aborting a cold one part way, the
                  retry re-evaluated 20,919 tokens in 33.5 seconds — the full
                  cold rate, having kept nothing. The prefix cache is real and
                  does make an agent&apos;s <em>next</em> turn nearly free, but
                  it never holds a prompt whose evaluation was cut off, which
                  is the only way this code is reached. Until 2026-08-14 this
                  page advised the opposite; following it bought another full
                  wait and the identical failure.
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
  );
}
