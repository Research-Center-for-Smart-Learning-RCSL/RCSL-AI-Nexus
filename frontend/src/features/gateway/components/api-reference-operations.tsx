import { CodeBlock } from '@/components/composed/code-block';

export function TimeoutSection() {
  return (
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
            long — and it is spent on what you sent rather than on the work the
            machine did. Reading the prompt is most of the work exactly once
            per conversation: measured on 2026-08-14, roughly 6% of the prompt
            tokens billed across one agent session were evaluated at all, and
            the rest were prefix-cache hits that cost the hardware nothing. The
            runtime reports the whole prompt either way, so the figure never
            moves and nothing here can tell the two apart.
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
  );
}


type ExtensionsSectionProps = {
  baseUrl: string;
};

export function ExtensionsSection({ baseUrl }: ExtensionsSectionProps) {
  return (
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
          table below for why retrying that one unchanged does not help.
        </p>
      </section>
  );
}
