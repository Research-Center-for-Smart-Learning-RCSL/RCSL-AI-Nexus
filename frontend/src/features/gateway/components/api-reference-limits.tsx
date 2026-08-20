import Link from 'next/link';

export function LimitsSection() {
  return (
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
        <p className="text-sm text-muted-foreground">
          <strong>
            There are no <code>x-ratelimit-*</code> response headers.
          </strong>{' '}
          OpenAI sends remaining-quota headers on every response and some
          client libraries read them; here the only signals are{' '}
          <code>429 rate_limited</code> / <code>quota_exceeded</code> when a
          limit is reached, each with <code>Retry-After</code>. A client that
          paces itself from the headers will simply not pace itself — listed
          rather than left to be discovered.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>The token quota is a rolling 24 hours, not a calendar day.</strong>{' '}
          Nothing resets at midnight, and an exhausted key does not come back
          all at once: each past request stops counting 24 hours after it was
          made, so the budget returns in the pieces it was spent in. The{' '}
          <code>Retry-After</code> on <code>quota_exceeded</code> is the
          projected moment enough of that spend has aged out, and the message
          states the same wait coarsely — “a moment” under 90 seconds, round
          minutes under an hour, and round hours above it.
        </p>
        <p className="text-sm text-muted-foreground">
          <strong>
            An exhausted quota does not stop <code>GET /v1/models</code>.
          </strong>{' '}
          It runs no model, so there is nothing for a token budget to charge,
          and every OpenAI-compatible client lists models before it can send
          anything. Gating it made a spent quota look like a broken connection.
          Every other check still applies to that call.
        </p>
      </section>
  );
}
