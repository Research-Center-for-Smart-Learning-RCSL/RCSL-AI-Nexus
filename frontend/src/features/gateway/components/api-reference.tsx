'use client';

import { useRef } from 'react';

import { ExportMarkdown } from '@/components/composed/export-markdown';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';
import { useAssistantSurface } from '@/features/assistant/context';
import { EndpointSection, CapabilitiesSection, RequestSection } from './api-reference-overview';
import { ResponseSection, ToolsSection, GroundingSection, StreamingSection } from './api-reference-contract';
import { TimeoutSection, ExtensionsSection } from './api-reference-operations';
import { ErrorsSection } from './api-reference-errors';
import { LimitsSection } from './api-reference-limits';

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

      <EndpointSection baseUrl={baseUrl} />

      <CapabilitiesSection capabilities={capabilities} sample={sample} isLoading={isLoading} />

      <RequestSection baseUrl={baseUrl} sample={sample} />

      <ResponseSection sample={sample} />

      <ToolsSection />

      <GroundingSection />

      <StreamingSection />

      <TimeoutSection />

      <ExtensionsSection baseUrl={baseUrl} />

      <ErrorsSection />

      <LimitsSection />
      </div>
    </div>
  );
}
