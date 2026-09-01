import { isValidElement, type ReactNode } from 'react';

export type ApiErrorRecord = {
  status: string;
  code: string;
  remediation: ReactNode;
  aliases?: readonly string[];
};

/**
 * The API reference's single authored error catalogue. Rich remediation stays
 * as React content so the table and Markdown export retain their formatting;
 * search derives plain text from the same nodes instead of duplicating prose.
 */
export const API_ERROR_CATALOGUE: readonly ApiErrorRecord[] = [
  {
    status: '400',
    code: 'untrusted_proxy',
    remediation: (
      <>
        The request did not arrive through this deployment&apos;s front door,
        so no source address could be established. It occurs where the
        application port is reached directly rather than the published endpoint
        above. Nothing about the key is at fault.
      </>
    ),
  },
  {
    status: '400',
    code: 'runtime_capability_unsupported',
    remediation: (
      <>
        Three conditions, none of them resolved by an identical retry. A{' '}
        <code>tool_choice</code> of <code>required</code> or of a named function,
        which no runtime here can enforce: send <code>auto</code>. A replayed
        assistant turn whose tool-call <code>arguments</code> do not parse as
        JSON, on a runtime that takes arguments as an object, as Ollama does:
        repair or discard that turn. Or, with <code>use_knowledge</code>, an
        embedding model on a runtime that cannot embed, in which case the
        request succeeds without the flag and an administrator must repoint the{' '}
        <code>embedding</code> policy.
      </>
    ),
  },
  {
    status: '401',
    code: 'not_authenticated',
    remediation: (
      <>
        Missing, malformed, unknown, expired or revoked key, or a source the
        key&apos;s CIDR allowlist does not permit. All return the same response
        by design: naming the condition would tell an attacker which one to
        address.
      </>
    ),
  },
  {
    status: '403',
    code: 'capability_not_issued',
    remediation: (
      <>
        The <code>model</code> field named something this key may not call, most
        often a client&apos;s own default model name rather than a capability.
        The message names what was requested and what may be requested instead;{' '}
        <code>GET /v1/models</code> returns the same list. Both are also
        available as fields — <code>capability</code> and <code>available</code>{' '}
        — so a client can branch on them rather than parse a sentence. Retrying
        does not succeed. A key may be issued with a default capability, which
        serves one of the key&apos;s own instead of refusing; the response then
        carries <code>X-Capability-Defaulted</code> naming what ran.
      </>
    ),
  },
  {
    status: '403',
    code: 'not_authorized',
    remediation: (
      <>
        The key may not perform this action at all: it holds none of the scopes
        the endpoint requires. Distinct from the row above, which concerns{' '}
        <em>which</em> capability was requested. This condition is not corrected
        by changing the <code>model</code> field.
      </>
    ),
  },
  {
    status: '403',
    code: 'country_not_allowed',
    remediation: (
      <>
        The request came from outside the countries this deployment accepts.
        Nothing about the key is at fault, so reissuing it has no effect. This is
        the second condition returning 403, and the reason to read the code
        rather than the status.
      </>
    ),
  },
  {
    status: '404',
    code: 'model_not_found',
    remediation: (
      <>
        Routing selected a model that its runtime does not hold. This is a
        deployment fault rather than a property of the request — the capability
        is configured but the weights behind it are absent — so an identical
        retry reproduces it. Two models can produce it: the one serving the
        requested capability and, with <code>use_knowledge</code>, the one
        serving <code>embedding</code>. In the second case the request succeeds
        without the flag.
      </>
    ),
  },
  {
    status: '422',
    code: 'invalid_request',
    remediation: (
      <>
        The request body did not match the schema, and <code>message</code> names
        the field and the rule. A missing <code>messages</code> array looks like
        this, as does a <code>tool</code> message with no{' '}
        <code>tool_call_id</code> and an image part in a <code>content</code>{' '}
        array.
      </>
    ),
  },
  {
    status: '429',
    code: 'rate_limited',
    remediation: (
      <>
        Requests per minute exceeded. <code>Retry-After</code> is set; the window
        is short and retrying is the correct response. The same figure appears
        in the body as <code>retry_after_seconds</code>, for clients that read
        bodies rather than headers.
      </>
    ),
  },
  {
    status: '429',
    code: 'quota_exceeded',
    remediation: (
      <>
        The key&apos;s token budget is spent. Carries{' '}
        <code>type: &quot;insufficient_quota&quot;</code>, not{' '}
        <code>rate_limit_error</code>, since retrying cannot succeed and an
        OpenAI client library branching on <code>type</code> stops rather than
        exhausting its backoff. <code>Retry-After</code> is a computed wait,
        described below; it is frequently many hours, and should be treated as a
        stop rather than as a delay. It appears in the body as{' '}
        <code>retry_after_seconds</code>, and is omitted from both rather than
        estimated where the recovery time cannot be projected.
      </>
    ),
  },
  {
    status: '413',
    code: 'context_too_long',
    remediation: (
      <>
        The prompt exceeds the configured input ceiling. Shorten it; the limit
        is a memory constraint rather than a policy, and an unchanged retry
        cannot succeed. The ceiling is{' '}
        <strong>at most 122,880 tokens</strong> across everything the model will
        read, tool definitions and replayed tool calls included, so an agent
        conversation reaches this through accumulation rather than through one
        large message. It is lower where a smaller model is serving the
        capability, which is why the response states the figure it was judged
        against rather than leaving the maximum to be assumed.
        <br />
        It carries its own arithmetic: <code>estimated</code> and{' '}
        <code>limit</code> as numbers, <code>composition</code>, which splits the
        figure across messages, prior tool calls and tool definitions and names
        the largest single message&apos;s share, and <code>basis</code>, which
        states how the figure was arrived at. The three shares have different
        remedies: an accumulated conversation is addressed by starting a new
        one, a single very large message by not reading that file in, and
        dominant tool definitions by reducing the client&apos;s tool list, which
        starting a new conversation does not affect. The same figures are
        repeated in <code>message</code> for clients that print only that field.
        <br />
        <code>basis</code> is one of three values and they are not
        interchangeable. <code>tokenizer</code> means the prompt was counted
        with the vocabulary and chat template of the model that would have read
        it, including the framing the runtime applies to each turn. It is the
        figure that model would have charged, and can be budgeted against
        directly. <code>estimate</code> means no vocabulary was available for
        that model and the figure was inferred from character widths. It runs
        roughly 20% to 60% above the true count on prose, source and tool schemas
        — the ratio is a property of the sample rather than a constant of the
        content type — and can run well below it on dense identifiers such as
        UUIDs or base64. Treat it as an upper bound on ordinary content and as no
        bound at all on the rest. <code>lower_bound</code> means the request was
        turned away before a model had been selected, on a bound that no
        tokenizer could bring under the ceiling. The true figure is above the
        number shown, and a payload producing this basis is in the order of a
        megabyte of text.
        <br />
        <strong>
          Every refusal is stored, and the account the key belongs to can read
          its own without an administrator.
        </strong>{' '}
        The code, the status, the message and these figures are retained against
        the <code>request_id</code> in the body for this deployment&apos;s
        refusal retention window — thirty days unless an administrator has
        changed it, and it may be set between 7 and 180 days — so a client that
        discards the response still leaves a record more useful than a container
        log. Nothing about the request itself is stored: no messages, no tool
        definitions, no model name.
      </>
    ),
  },
  {
    status: '413',
    code: 'request_too_large',
    remediation: (
      <>
        The request body itself is over the platform&apos;s byte ceiling, which
        is a separate limit from the row above and is measured differently. That
        limit counts tokens in what the model will read and is applied after the
        request is parsed and the key is checked; this one counts raw bytes and
        is applied before either, so it is the only error here that can be
        received without a valid key. In practice it is reached only by sending
        something far larger than the context ceiling would permit in any case:
        a whole file pasted into a message, or a body other than the one
        intended.
      </>
    ),
  },
  {
    status: '503',
    code: 'no_available_model',
    remediation: (
      <>
        The routing layer found nothing to send the request to: no policy names
        the capability, every candidate is offline or unloaded, or the runtime
        process refused the connection. The response does not distinguish
        between them. Retry with backoff; where the condition persists, the
        deployment requires an administrator. The two rows below are distinct
        codes with different remedies, and an integration branching on this one
        alone should be updated to recognise them.
      </>
    ),
  },
  {
    status: '503',
    code: 'runtime_timeout',
    remediation: (
      <>
        The runtime took longer than the platform&apos;s read timeout before
        producing its first byte, almost always prompt evaluation on a large
        context.{' '}
        <strong>An unchanged retry is unlikely to succeed; send less.</strong> A
        cancelled prefill is discarded rather than retained. Measured on this
        deployment by aborting a cold prefill part way, the retry re-evaluated
        20,919 tokens in 33.5 seconds, the full cold rate, having retained
        nothing. The prefix cache does make an agent&apos;s <em>next</em> turn
        nearly free, but it never holds a prompt whose evaluation was
        interrupted, which is the only condition under which this code is
        returned.
      </>
    ),
  },
  {
    status: '503',
    code: 'overloaded',
    remediation: (
      <>
        Every inference slot was busy for the duration of the queue wait, which
        is two minutes. The deployment is healthy and at capacity.{' '}
        <code>Retry-After</code> is set, and backing off for that interval is the
        correct response. It is distinct from <code>no_available_model</code>,
        which reports a deployment that cannot serve the request at all.
      </>
    ),
  },
  {
    status: '—',
    code: 'stream_interrupted',
    aliases: ['stream marker'],
    remediation: (
      <>
        Returned only in the mid-stream error frame above, or, rarely, as a 503
        where the runtime&apos;s stream ended before producing anything: the
        generation stalled, or its stream ended without a terminal event. A
        partial answer may have been received. Whether to retry is a question of
        the caller&apos;s idempotence, since the platform has no knowledge of
        what already-executed tool calls have done.
      </>
    ),
  },
  {
    status: '500',
    code: 'internal_error',
    remediation: (
      <>
        A condition the platform did not anticipate. It carries the same
        envelope as every other error. The traceback is written to the log; the
        response carries <code>error.request_id</code>, and quoting that
        identifier is how an administrator locates the traceback. Retry once;
        where it recurs, report the identifier.
      </>
    ),
  },
] as const;

function nodeText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join(' ');
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return nodeText(node.props.children);
  }
  return '';
}

function normaliseSearchText(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
}

export function matchesApiError(error: ApiErrorRecord, query: string): boolean {
  const trimmedQuery = query.trim();
  if (!trimmedQuery) return true;

  // The visible status-less marker is punctuation rather than a word. Match it
  // as a status before general punctuation becomes a search boundary; mapping
  // every em dash to text would make ordinary remediation dashes false aliases.
  if (trimmedQuery === '—') return error.status === '—';

  const needle = normaliseSearchText(query);
  // A non-blank punctuation-only query is still a real query. Treating it as
  // blank makes inputs such as "???" silently reset the filter.
  if (!needle) return false;

  const haystack = normaliseSearchText(
    [
      error.status,
      error.code,
      nodeText(error.remediation),
      ...(error.aliases ?? []),
    ].join(' '),
  );
  return haystack.includes(needle);
}
