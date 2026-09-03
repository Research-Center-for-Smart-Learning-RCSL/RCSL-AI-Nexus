import { CodeBlock } from '@/components/composed/code-block';
import { Badge } from '@/components/ui/badge';
import {
  ApiReferenceSectionLayout,
  type ApiReferenceSectionProps,
} from './api-reference-section';

type EndpointSectionProps = {
  baseUrl: string;
};

export function EndpointSection({
  baseUrl,
  section,
}: EndpointSectionProps & ApiReferenceSectionProps) {
  return (
      <ApiReferenceSectionLayout section={section}>
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
      </ApiReferenceSectionLayout>
  );
}


type CapabilitiesSectionProps = {
  capabilities: string[];
  sample: string;
  isLoading: boolean;
};

export function CapabilitiesSection({
  capabilities,
  sample,
  isLoading,
  section,
}: CapabilitiesSectionProps & ApiReferenceSectionProps) {
  return (
      <ApiReferenceSectionLayout section={section}>
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
              Loading capabilities…
            </span>
          ) : capabilities.length ? (
            capabilities.map((capability) => (
              <Badge key={capability} variant="outline" className="font-mono">
                {capability}
              </Badge>
            ))
          ) : (
            <span className="text-sm text-muted-foreground">
              Nothing is routable. An administrator must bind a routing policy
              to a registered model before any request can be served.
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          The same list is available on the wire as{' '}
          <code>GET /v1/models</code>, in OpenAI&apos;s shape, narrowed to what
          the key was issued for. A key is refused any capability it does not
          carry, unless it was issued with a default capability, which serves
          one of the key&apos;s own capabilities instead of refusing. A key
          issued for <code>chat</code> therefore cannot consume capacity on
          anything else.
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
      </ApiReferenceSectionLayout>
  );
}


type RequestSectionProps = {
  baseUrl: string;
  sample: string;
};

export function RequestSection({
  baseUrl,
  sample,
  section,
}: RequestSectionProps & ApiReferenceSectionProps) {
  return (
      <ApiReferenceSectionLayout section={section}>
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
            honours the supplied value only where it is stricter. A truncated
            generation reports{' '}
            <code>finish_reason: &quot;length&quot;</code>, never{' '}
            <code>stop</code>.
          </dd>
          <dt className="font-mono text-muted-foreground">think</dt>
          <dd>
            An extension, not part of the OpenAI schema. Omit to take the
            deployment default; <code>false</code> asks a deliberating model to
            answer directly. A model&apos;s reasoning comes back as{' '}
            <code>reasoning_content</code> and is never merged into{' '}
            <code>content</code>: returning it as history would supply the model
            with its own intermediate reasoning.
          </dd>
          <dt className="font-mono text-muted-foreground">use_knowledge</dt>
          <dd>
            An extension. Retrieves from the tenant&apos;s knowledge base and
            grounds the answer on the result. Disabled by default, since
            grounding costs an embedding call and a share of the context window,
            and is therefore requested rather than assumed. The grounding
            section below states what it does and does not guarantee.
          </dd>
          <dt className="font-mono text-muted-foreground">
            knowledge_collection
          </dt>
          <dd>
            Restricts retrieval to one collection. Ignored unless{' '}
            <code>use_knowledge</code> is set. It can only narrow: the tenant
            scope is fixed by the key, and no value here widens it.
          </dd>
          <dt className="font-mono text-muted-foreground">prompt_template</dt>
          <dd>
            An extension. Names one of the tenant&apos;s saved prompt
            templates, whose text is placed at the front of the conversation,
            ahead of any system message the caller sends, which is retained
            rather than replaced. There is no substitution: a template is fixed
            text, and the caller selects which template applies rather than what
            it says. A name that does not resolve returns <code>404</code>, so a
            request never proceeds without the template it specified.
          </dd>
        </dl>
        <p className="text-sm text-muted-foreground">
          <strong>
            <code>think</code>, <code>use_knowledge</code>,{' '}
            <code>knowledge_collection</code> and{' '}
            <code>prompt_template</code> are not OpenAI schema fields
          </strong>
          , and the official SDKs reject unknown named arguments rather than
          forwarding them. Send them through the SDK&apos;s pass-through
          mechanism; in Python, <code>extra_body</code>:
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
            Honoured, and forwarded only when set, so the model&apos;s own
            defaults otherwise remain in force. <code>stop</code> accepts a
            string or up to four of them.
          </dd>
          <dt className="font-mono text-muted-foreground">stream_options</dt>
          <dd>
            <code>{'{"include_usage": true}'}</code> adds a final frame carrying
            token counts before <code>[DONE]</code>. Disabled unless requested,
            because that frame carries an empty <code>choices</code> array and a
            client not expecting it may treat it as malformed.
          </dd>
        </dl>
        <p className="text-sm text-muted-foreground">
          <strong>
            Every other field is accepted and silently ignored.
          </strong>{' '}
          The fields most likely to be expected to take effect, and which do
          not:{' '}
          <code>response_format</code>, <code>parallel_tool_calls</code>,{' '}
          <code>frequency_penalty</code> and <code>presence_penalty</code>.
          Four requests are refused rather than ignored, because serving them
          incorrectly would be worse than refusing them: <code>n</code> other
          than <code>1</code>; a <code>tool_choice</code> of{' '}
          <code>required</code> or of a named function; the deprecated{' '}
          <code>functions</code> and <code>function_call</code> spellings, for
          which <code>tools</code> and <code>tool_choice</code> should be sent
          instead; and <code>stream_options</code> on a request whose{' '}
          <code>stream</code> is not <code>true</code>.
        </p>
      </ApiReferenceSectionLayout>
  );
}
