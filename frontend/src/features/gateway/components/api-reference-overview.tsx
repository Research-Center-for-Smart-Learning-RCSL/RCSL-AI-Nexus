import { CodeBlock } from '@/components/composed/code-block';
import { Badge } from '@/components/ui/badge';

type EndpointSectionProps = {
  baseUrl: string;
};

export function EndpointSection({ baseUrl }: EndpointSectionProps) {
  return (
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
  );
}


type CapabilitiesSectionProps = {
  capabilities: string[];
  sample: string;
  isLoading: boolean;
};

export function CapabilitiesSection({ capabilities, sample, isLoading }: CapabilitiesSectionProps) {
  return (
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
          carry — unless it was issued with a default capability, which serves
          one of its own instead of refusing — so a key issued for{' '}
          <code>chat</code> cannot spend the hardware&apos;s time on anything
          else.
        </p>
        <CodeBlock
          code={`{
  "object": "list",
  "data": [
    {"id": "${sample}", "object": "model", "created": 0, "owned_by": "rcsl-ai-nexus"}
  ]
}`}
          label="Copy the /v1/models shape"
        />
      </section>
  );
}


type RequestSectionProps = {
  baseUrl: string;
  sample: string;
};

export function RequestSection({ baseUrl, sample }: RequestSectionProps) {
  return (
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
  );
}
