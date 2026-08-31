'use client';

import { useMemo, useState } from 'react';

import { CodeBlock } from '@/components/composed/code-block';
import { EmptyState } from '@/components/composed/empty-state';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  API_ERROR_CATALOGUE,
  matchesApiError,
} from './api-reference-error-catalogue';

export function ErrorsSection() {
  const [query, setQuery] = useState('');
  const matches = useMemo(
    () => API_ERROR_CATALOGUE.filter((error) => matchesApiError(error, query)),
    [query],
  );
  const matchingCodes = new Set(matches.map((error) => error.code));
  const hasResults = matches.length > 0;

  return (
    <section className="space-y-3">
      <h2 className="font-heading text-base font-semibold">Errors</h2>
      <div className="max-w-xl space-y-1.5" data-md-skip>
        <label htmlFor="api-error-search" className="text-sm font-medium">
          Search errors
        </label>
        <Input
          id="api-error-search"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Status, error code, or remediation"
          autoComplete="off"
        />
        <p aria-live="polite" aria-atomic="true" className="sr-only">
          {matches.length} of {API_ERROR_CATALOGUE.length} errors shown.
        </p>
      </div>
      <p className="text-sm text-muted-foreground">
        Every failure the platform raises carries{' '}
        <code>
          {'{"error": {"type": "...", "code": "...", "message": "..."}}'}
        </code>
        . <code>type</code> is OpenAI&apos;s coarse classification, usually
        derived from the status; <code>code</code> is this platform&apos;s and
        is the more precise of the two. Branch on one of them rather than on the
        status: 429, 403 and 400 each cover two different conditions, and each
        needs different handling. Where the status would classify two remedies
        alike, <code>type</code> is set from the condition instead — a spent
        quota is <code>insufficient_quota</code> rather than the{' '}
        <code>rate_limit_error</code> its 429 would otherwise imply.
      </p>
      <p className="text-sm text-muted-foreground">
        <strong>
          Every response carries <code>X-Request-Id</code>
        </strong>
        , and every error body repeats it as <code>error.request_id</code>. The
        detail behind an error is never included in the response; it is written
        to the platform&apos;s log, keyed by this identifier. When reporting a
        failure, <strong>quote the identifier</strong>: it is the difference
        between an administrator searching timestamps and locating the exact
        entry. While an integration is being debugged, an administrator can open
        a time-boxed <em>debug window</em> on the key, from the API keys page,
        during which error responses carry that detail directly as{' '}
        <code>error.detail</code>.
      </p>
      <h3 className="pt-2 font-heading text-sm font-semibold">
        A stream that fails after it has started
      </h3>
      <p className="text-sm text-muted-foreground">
        The table below describes failures that happen before any bytes are sent,
        which receive a status code. Once the first frame has been sent, the
        status line is committed as 200 and cannot be withdrawn, so a failure
        mid-generation arrives in the body instead: a frame carrying{' '}
        <code>error.code</code> and <code>error.message</code>, and then{' '}
        <strong>
          the stream ends without <code>data: [DONE]</code>
        </strong>
        . This frame carries no <code>type</code>: it is written by the stream
        itself rather than by the error response above, so <code>code</code> is
        the only field to branch on here.
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

      {!hasResults ? (
        <div data-md-skip>
          <EmptyState
            title="No matching errors"
            description={`No status, error code, or remediation matches “${query}”.`}
            action={
              <Button
                type="button"
                variant="outline"
                onClick={() => setQuery('')}
              >
                Clear search
              </Button>
            }
            className="py-8"
          />
        </div>
      ) : null}

      {/* Hidden rows remain in the DOM deliberately: Markdown export walks the
          authored table rather than its visual state, so a filtered screen can
          never produce incomplete reference documentation. */}
      <div className="overflow-x-auto" hidden={!hasResults}>
        <table className="w-full text-left text-sm">
          <thead className="text-muted-foreground">
            <tr className="border-b">
              <th className="py-2 pr-4 font-medium">Status</th>
              <th className="py-2 pr-4 font-medium">Code</th>
              <th className="py-2 font-medium">What to do</th>
            </tr>
          </thead>
          <tbody className="[&_td]:py-2 [&_td]:pr-4 [&_tr]:border-b">
            {API_ERROR_CATALOGUE.map((error) => (
              <tr key={error.code} hidden={!matchingCodes.has(error.code)}>
                <td>{error.status}</td>
                <td className="font-mono text-xs">{error.code}</td>
                <td>{error.remediation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
