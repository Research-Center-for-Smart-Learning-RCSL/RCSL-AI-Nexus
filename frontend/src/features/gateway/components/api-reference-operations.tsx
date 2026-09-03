import { CodeBlock } from '@/components/composed/code-block';

import {
  ApiReferenceSectionLayout,
  type ApiReferenceSectionProps,
} from './api-reference-section';

export function TimeoutSection({ section }: ApiReferenceSectionProps) {
  return (
      <ApiReferenceSectionLayout section={section}>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="font-mono text-muted-foreground">finish_reason</dt>
          <dd>
            <code>stop</code> indicates that the model finished.{' '}
            <code>length</code> indicates that the answer was truncated, either
            at the token ceiling or at the platform&apos;s wall-clock deadline
            for a single generation. The two are not distinguishable from the
            response, and both carry the same consequence: the reply is
            incomplete, and whether to continue it is the caller&apos;s
            decision. <code>tool_calls</code> indicates that the model has
            requested a tool run and is awaiting the result.
          </dd>
          <dt className="font-mono text-muted-foreground">usage</dt>
          <dd>
            All three figures are reported, and <code>total_tokens</code> is the
            sum of both sides. A key&apos;s quota is spent by that same total, so
            a large prompt is charged whether or not the answer is long, and it
            is charged on what was sent rather than on the work performed.
            Reading the prompt constitutes most of that work exactly once per
            conversation: measured across one agent session on this deployment,
            roughly 6% of the prompt tokens charged were evaluated at all, and
            the remainder were prefix-cache hits that cost the hardware nothing.
            The runtime reports the whole prompt in either case, so the figure
            does not move and nothing in the response distinguishes the two.
            <br />
            <strong>One exception applies.</strong> Where the caller disconnects
            before the response completes, <code>prompt_tokens</code> is
            recorded as <code>0</code> for that call. The runtime reports the
            figure only with its final chunk, so an abandoned request is
            under-counted rather than estimated.
          </dd>
          <dt className="font-mono text-muted-foreground">
            usage, when streaming
          </dt>
          <dd>
            Sent only on request, with{' '}
            <code>{'"stream_options": {"include_usage": true}'}</code>. The
            figures arrive in a frame of their own after the terminal one and
            before <code>[DONE]</code>, with an empty <code>choices</code>{' '}
            array. Without that option a streamed response carries no{' '}
            <code>usage</code> at all. A stream that failed carries none in
            either case, since the counts would describe work that did not
            finish.
          </dd>
        </dl>
        <p className="text-sm text-muted-foreground">
          <strong>The full frame sequence of one streamed answer</strong>, with
          every optional frame present. Each is an ordinary OpenAI chunk; what
          varies is the key the delta carries. The order is contractual: in
          particular <code>tool_calls</code> always precedes the terminal frame,
          because a client that has read <code>finish_reason</code> has stopped
          reading deltas.
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
      </ApiReferenceSectionLayout>
  );
}


type ExtensionsSectionProps = {
  baseUrl: string;
};

export function ExtensionsSection({
  baseUrl,
  section,
}: ExtensionsSectionProps & ApiReferenceSectionProps) {
  return (
      <ApiReferenceSectionLayout section={section}>
        <p className="text-sm text-muted-foreground">
          <strong>
            The first token of a large request can legitimately take close to
            twenty minutes to arrive.
          </strong>{' '}
          Prompt evaluation produces no bytes while it runs, so a conversation
          near the context ceiling produces minutes of silence before anything
          streams. That silence is work rather than failure. Two bounds apply in
          sequence and compose: the platform allows up to 20 minutes
          between bytes from the runtime, which is what bounds reading the
          prompt, and up to 15 minutes of wall clock for writing the answer,
          counted from the first chunk. One request&apos;s worst case, end to
          end, is therefore <strong>35 minutes</strong>.
        </p>
        <p className="text-sm text-muted-foreground">
          Most SDK defaults are shorter than that. The OpenAI Python
          SDK&apos;s default overall timeout is 600 seconds, so on a long agent
          conversation <em>the client</em> abandons the request first, and the
          resulting connection error is indistinguishable from a platform
          failure. Set the client&apos;s timeout to at least 2100 seconds for
          agent workloads:
        </p>
        <CodeBlock
          code={`client = OpenAI(base_url="${baseUrl}/v1", api_key=key, timeout=2100.0)`}
          label="Copy the timeout example"
        />
        <p className="text-sm text-muted-foreground">
          Two further waits are bounded and reported. A request arriving while
          every inference slot is busy queues for at most two minutes and is
          then refused as <code>503 overloaded</code> with{' '}
          <code>Retry-After</code>. A runtime that exceeds the platform&apos;s
          own read timeout returns <code>503 runtime_timeout</code>; the table
          below states why an unchanged retry of that condition does not
          succeed.
        </p>
      </ApiReferenceSectionLayout>
  );
}
