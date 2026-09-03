import Link from 'next/link';

import {
  ApiReferenceSectionLayout,
  type ApiReferenceSectionProps,
} from './api-reference-section';

export function LimitsSection({ section }: ApiReferenceSectionProps) {
  return (
      <ApiReferenceSectionLayout section={section}>
        <p className="text-sm text-muted-foreground">
          Each key carries its own requests-per-minute limit and daily token
          quota, and optionally a list of source addresses it may be used from.
          They are visible on the{' '}
          <Link href="/api-keys" className="underline">
            API keys
          </Link>{' '}
          page. The source allowlist is the only control that remains effective
          after a key has been disclosed, so set it wherever the caller has a
          fixed address.
        </p>
        <p className="text-sm text-muted-foreground">
          Every key expires, and expiry cannot be disabled. It is what compels
          rotation. A key can be extended from the same page before it lapses,
          which does not change the secret and requires no redeployment.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>
            There are no <code>x-ratelimit-*</code> response headers.
          </strong>{' '}
          OpenAI sends remaining-quota headers on every response and some
          client libraries read them. Here the only signals are{' '}
          <code>429 rate_limited</code> and <code>quota_exceeded</code> when a
          limit is reached, each with <code>Retry-After</code>. A client that
          paces itself from those headers will not pace itself at all, which is
          stated here rather than left to be discovered.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>The token quota is a rolling 24 hours, not a calendar day.</strong>{' '}
          Nothing resets at midnight, and an exhausted key does not recover all
          at once: each past request ceases to count 24 hours after it was made,
          so the budget returns in the increments in which it was spent. The{' '}
          <code>Retry-After</code> on <code>quota_exceeded</code> is the
          projected point at which sufficient consumption has aged out, and the
          message states the same interval approximately: “a moment” below 90
          seconds, whole minutes below an hour, and whole hours above it.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>
            An exhausted quota does not stop <code>GET /v1/models</code>.
          </strong>{' '}
          It runs no model, so there is nothing for a token budget to charge,
          and every OpenAI-compatible client lists models before it can send
          anything. Applying the quota to that call would make an exhausted
          budget indistinguishable from a broken connection. Every other check
          continues to apply to it.
        </p>
      </ApiReferenceSectionLayout>
  );
}
