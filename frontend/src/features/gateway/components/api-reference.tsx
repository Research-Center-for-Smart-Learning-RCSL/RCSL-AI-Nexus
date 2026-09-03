'use client';

import {
  type MouseEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';

import { ExportMarkdown } from '@/components/composed/export-markdown';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';
import { useAssistantSurface } from '@/features/assistant/context';
import { EndpointSection, CapabilitiesSection, RequestSection } from './api-reference-overview';
import { ResponseSection, ToolsSection, GroundingSection, StreamingSection } from './api-reference-contract';
import { TimeoutSection, ExtensionsSection } from './api-reference-operations';
import { ErrorsSection } from './api-reference-errors';
import { LimitsSection } from './api-reference-limits';
import {
  API_REFERENCE_SECTION_CATALOGUE,
  apiReferenceHeadingId,
  apiReferenceSectionTitleText,
  isApiReferenceSectionId,
  type ApiReferenceSection,
  type ApiReferenceSectionId,
} from './api-reference-section-catalogue';

const READING_OFFSET_PX = 16;
// Browser layout commonly lands an explicit jump a fraction below the exact
// target (for example 15.999px for a 16px offset). Treat that sub-pixel result
// as aligned so scrollspy does not immediately advance to the next heading.
const READING_OFFSET_TOLERANCE_PX = 1;

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
  const [activeSectionId, setActiveSectionId] =
    useState<ApiReferenceSectionId>(API_REFERENCE_SECTION_CATALOGUE[0].id);

  const jumpToSection = useCallback(
    (
      id: ApiReferenceSectionId,
      options: { updateHash?: boolean; focus?: boolean; smooth?: boolean } = {},
    ) => {
      const main = content.current?.closest('main');
      const heading = document.getElementById(apiReferenceHeadingId(id));
      if (!(main instanceof HTMLElement) || !heading) return;

      const mainRect = main.getBoundingClientRect();
      const headingRect = heading.getBoundingClientRect();
      const reducedMotion =
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;

      main.scrollTo({
        top: Math.max(
          0,
          main.scrollTop + headingRect.top - mainRect.top - READING_OFFSET_PX,
        ),
        behavior: options.smooth && !reducedMotion ? 'smooth' : 'auto',
      });
      setActiveSectionId(id);

      if (options.updateHash) {
        window.history.replaceState(
          window.history.state,
          '',
          `${window.location.pathname}${window.location.search}#${id}`,
        );
      }
      if (options.focus) heading.focus({ preventScroll: true });
    },
    [],
  );

  // A fragment target must be scrolled inside the shell's main region. The
  // browser's default document-fragment restoration cannot know that the
  // document itself is fixed while this nested region owns all scrolling.
  useEffect(() => {
    let frame: number | undefined;
    const jumpToCurrentHash = () => {
      // Catalogue ids are deliberately ASCII. Comparing the raw fragment also
      // means a malformed percent escape is ignored instead of throwing from an
      // effect and replacing otherwise usable documentation with an error page.
      const id = window.location.hash.slice(1);
      if (!isApiReferenceSectionId(id)) return;

      if (frame !== undefined) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        frame = undefined;
        jumpToSection(id, { smooth: false });
      });
    };

    jumpToCurrentHash();
    window.addEventListener('hashchange', jumpToCurrentHash);
    window.addEventListener('popstate', jumpToCurrentHash);
    return () => {
      if (frame !== undefined) window.cancelAnimationFrame(frame);
      window.removeEventListener('hashchange', jumpToCurrentHash);
      window.removeEventListener('popstate', jumpToCurrentHash);
    };
  }, [jumpToSection]);

  useEffect(() => {
    const main = content.current?.closest('main');
    if (
      !(main instanceof HTMLElement) ||
      typeof IntersectionObserver !== 'function'
    ) {
      return;
    }

    const headings = API_REFERENCE_SECTION_CATALOGUE.map((section) => ({
      id: section.id,
      heading: document.getElementById(apiReferenceHeadingId(section.id)),
    })).filter(
      (candidate): candidate is {
        id: ApiReferenceSectionId;
        heading: HTMLElement;
      } => candidate.heading instanceof HTMLElement,
    );

    const updateActiveSection = () => {
      const rootRect = main.getBoundingClientRect();
      const readingTop = rootRect.top + READING_OFFSET_PX;
      const positions = headings.map(({ id, heading }) => ({
        id,
        top: heading.getBoundingClientRect().top,
      }));
      const nextHeading = positions.find(
        ({ top }) =>
          top >= readingTop - READING_OFFSET_TOLERANCE_PX &&
          top < rootRect.bottom,
      );
      const precedingHeading = positions
        .slice()
        .reverse()
        .find(({ top }) => top < readingTop - READING_OFFSET_TOLERANCE_PX);
      setActiveSectionId(
        nextHeading?.id ??
          precedingHeading?.id ??
          API_REFERENCE_SECTION_CATALOGUE[0].id,
      );
    };

    const observer = new IntersectionObserver(updateActiveSection, {
      root: main,
      rootMargin: `-${READING_OFFSET_PX}px 0px 0px 0px`,
      // Zero reports entry/exit. One reports the second boundary needed when
      // scrolling upward: a short heading first enters the root partially,
      // then becomes fully visible as its top crosses the reading offset.
      threshold: [0, 1],
    });
    headings.forEach(({ heading }) => observer.observe(heading));
    updateActiveSection();

    return () => observer.disconnect();
  }, []);

  function onSectionLink(
    event: MouseEvent<HTMLAnchorElement>,
    id: ApiReferenceSectionId,
  ) {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    event.preventDefault();
    jumpToSection(id, { updateHash: true, focus: true, smooth: true });
  }

  function renderSection(section: ApiReferenceSection) {
    switch (section.renderKey) {
      case 'endpoint':
        return <EndpointSection key={section.id} section={section} baseUrl={baseUrl} />;
      case 'capabilities':
        return (
          <CapabilitiesSection
            key={section.id}
            section={section}
            capabilities={capabilities}
            sample={sample}
            isLoading={isLoading}
            isUnavailable={Boolean(error)}
          />
        );
      case 'request':
        return (
          <RequestSection
            key={section.id}
            section={section}
            baseUrl={baseUrl}
            sample={sample}
          />
        );
      case 'tool-calling':
        return <ResponseSection key={section.id} section={section} sample={sample} />;
      case 'wire-protocols':
        return <ToolsSection key={section.id} section={section} />;
      case 'grounding':
        return <GroundingSection key={section.id} section={section} />;
      case 'model-limitations':
        return <StreamingSection key={section.id} section={section} />;
      case 'response':
        return <TimeoutSection key={section.id} section={section} />;
      case 'timeouts':
        return (
          <ExtensionsSection
            key={section.id}
            section={section}
            baseUrl={baseUrl}
          />
        );
      case 'errors':
        return <ErrorsSection key={section.id} section={section} />;
      case 'limits':
        return <LimitsSection key={section.id} section={section} />;
    }
  }

  return (
    <div className="@container space-y-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between @4xl:justify-end">
        <div className="space-y-1 @4xl:hidden" data-md-skip>
          <label htmlFor="api-reference-section-jump" className="text-sm font-medium">
            Jump to section
          </label>
          <select
            id="api-reference-section-jump"
            value={activeSectionId}
            onChange={(event) =>
              jumpToSection(event.target.value as ApiReferenceSectionId, {
                updateHash: true,
                focus: true,
                smooth: true,
              })
            }
            className="block h-9 w-full max-w-sm rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 sm:w-auto sm:min-w-64"
          >
            {API_REFERENCE_SECTION_CATALOGUE.map((section) => (
              <option key={section.id} value={section.id}>
                {apiReferenceSectionTitleText(section)}
              </option>
            ))}
          </select>
        </div>
        <ExportMarkdown
          contentRef={content}
          title="API reference"
          filename="rcsl-ai-nexus-api-reference"
        />
      </div>
      <div className="@4xl:grid @4xl:grid-cols-[13rem_minmax(0,1fr)] @4xl:gap-8">
        <nav
          aria-label="API Reference sections"
          className="hidden @4xl:block"
          data-md-skip
        >
          <div className="sticky top-4 max-h-[calc(100dvh-6rem)] overflow-y-auto overscroll-contain pr-2">
            <p className="mb-3 text-sm font-semibold">On this page</p>
            <ol className="space-y-1 border-l pl-3">
              {API_REFERENCE_SECTION_CATALOGUE.map((section) => {
                const active = section.id === activeSectionId;
                return (
                  <li key={section.id}>
                    <a
                      href={`#${section.id}`}
                      aria-current={active ? 'location' : undefined}
                      onClick={(event) => onSectionLink(event, section.id)}
                      className={
                        active
                          ? 'block rounded-sm py-1 text-sm font-medium text-foreground'
                          : 'block rounded-sm py-1 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
                      }
                    >
                      {apiReferenceSectionTitleText(section)}
                    </a>
                  </li>
                );
              })}
            </ol>
          </div>
        </nav>
        <div
          ref={content}
          data-api-reference-content
          className="min-w-0 space-y-8"
        >
          {/* An inline notice, not an early return. Only the origin and the
              capability badges come from the network; the header format, the
              capability convention, the request fields and the error table are the
              contract itself, and §4.4 traded `/openapi.json` away for them. They
              must not disappear because one call failed. */}
          {error ? (
            <div
              role="alert"
              className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 p-4"
            >
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

          {API_REFERENCE_SECTION_CATALOGUE.map(renderSection)}
        </div>
      </div>
    </div>
  );
}
