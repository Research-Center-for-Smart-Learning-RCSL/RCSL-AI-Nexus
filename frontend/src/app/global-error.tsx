'use client';

/**
 * The last resort: a throw in the root layout itself, above every provider.
 *
 * This one replaces the whole document, so it must render its own `html` and
 * `body` and cannot use anything that depends on the providers — no theme, no
 * query client, no session. Deliberately plain for that reason.
 */

import { useEffect } from 'react';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Unhandled root error', error.digest ?? '', error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          display: 'flex',
          minHeight: '100vh',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '1.5rem',
          fontFamily: 'system-ui, sans-serif',
          textAlign: 'center',
        }}
      >
        <div style={{ maxWidth: '28rem' }}>
          <h1 style={{ fontSize: '1.125rem', fontWeight: 600 }}>
            RCSL AI Nexus could not start
          </h1>
          <p style={{ marginTop: '0.5rem', fontSize: '0.875rem' }}>
            The management UI failed before it could render. Reloading is worth
            one attempt; if it repeats, an administrator needs the time this
            happened.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: '1rem',
              padding: '0.375rem 0.75rem',
              fontSize: '0.875rem',
              borderRadius: '0.5rem',
              border: '1px solid currentColor',
              background: 'transparent',
              cursor: 'pointer',
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
