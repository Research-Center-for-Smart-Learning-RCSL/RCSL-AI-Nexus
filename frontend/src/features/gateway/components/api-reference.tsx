'use client';

import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { CodeBlock } from '@/components/composed/code-block';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';

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
 * `api.nexus.rcsl.online` would be wrong on every other deployment and nobody
 * would notice.
 */
export function ApiReference() {
  const { data, isLoading, error, refetch } = useGatewayInfo();

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
        </dl>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">Errors</h2>
        <p className="text-sm text-muted-foreground">
          Every failure the platform raises carries{' '}
          <code>{'{"error": {"code": "...", "message": "..."}}'}</code>. Branch
          on the code rather than the status: two different conditions share
          429, and two share 403, and each pair needs different handling. The
          one exception is a request the schema rejects before any of this runs
          — see 422 below, which has the framework&apos;s shape instead.
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
                <td>422</td>
                <td className="font-mono text-xs">—</td>
                <td>
                  The request body did not match the schema. Raised by the
                  framework before the platform sees it, so this one carries{' '}
                  <code>{'{"detail": [...]}'}</code> rather than the envelope
                  above. A missing <code>messages</code> array looks like this.
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
                  The daily token quota is spent. Retrying inside the same day
                  cannot succeed, so back off until it resets rather than
                  looping.
                </td>
              </tr>
              <tr>
                <td>413</td>
                <td className="font-mono text-xs">context_too_long</td>
                <td>
                  The prompt exceeds the configured input ceiling. Shorten it;
                  the limit is about memory, not policy.
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
                  administrator.
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
