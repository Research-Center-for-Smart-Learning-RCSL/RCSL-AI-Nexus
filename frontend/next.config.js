/** @type {import('next').NextConfig} */

// The /admin proxy lives in src/middleware.ts, not here. A rewrites() entry is
// resolved at build time and serialised into the standalone bundle, so the
// destination cannot differ between the two entrances that share this image,
// and an unset ADMIN_API_URL bakes in a fallback that fails at runtime rather
// than at build. See the comment at the top of that file.

// Standalone output is what the Dockerfile ships, but producing it requires
// creating symlinks, which Windows refuses without Developer Mode. Gating it
// on an env var keeps `pnpm build` usable on the development machine while
// the image build (on macOS) still gets a self-contained bundle.
const STANDALONE = process.env.NEXT_OUTPUT === 'standalone';

// The Playwright runner builds with a test CSRF cookie name inlined into the
// client bundle, which must not be mistaken for a deployable build. Pointing
// that run at its own directory keeps it out of the `.next` that `pnpm build`
// and `pnpm dev` produce. Unset everywhere else, including in the image build.
const DIST_DIR = process.env.NEXT_DIST_DIR;

const nextConfig = {
  ...(STANDALONE ? { output: 'standalone' } : {}),
  // A build writes its own generated types back into the tsconfig it was given.
  // Left pointing at tsconfig.json, the e2e build edits a tracked file on every
  // run — a dirty working tree after running the tests, and a test-only path in
  // the configuration that ships. It gets its own file to edit instead.
  ...(DIST_DIR
    ? { distDir: DIST_DIR, typescript: { tsconfigPath: 'tsconfig.e2e.json' } }
    : {}),
  reactStrictMode: true,
  experimental: {
    // The middleware proxies /admin/* with NextResponse.rewrite, and Next
    // applies a socket timeout to a proxied request: `proxyTimeout || 30000`
    // in server/lib/router-utils/proxy-request.js. Thirty seconds is a
    // reasonable default for an API call and wrong for an SSE generation,
    // which is idle by design between tokens and can be idle for its whole
    // length while a thinking model deliberates. It cut a 93-second answer at
    // exactly 30s, and the browser saw a 500 with no trace in the backend log
    // — the reset happened between the two containers. See PROGRESS 2026-07-27.
    //
    // Sized above the longest a backend request can legitimately take, so the
    // guardrail that fires is the one that can report a reason: this timeout
    // resets the socket and says nothing, while the backend's deadline ends
    // the stream with finish_reason=length.
    //
    // **That is REQUEST_TIMEOUT_SECONDS + GENERATION_DEADLINE_SECONDS, not the
    // deadline alone.** Since 2026-08-05 the deadline is counted from the first
    // chunk rather than from the request, so a long prompt may spend up to the
    // read timeout being evaluated *before* the deadline's clock even starts.
    // The two compose: 600 + 900 = 1500s. Comparing against 900 alone left the
    // proxy cutting at 960s, which is the original silent reset moved from 30
    // seconds to 16 minutes. `test_config_failfast.py` reads both files and
    // fails if this drops below the sum, because a comment cannot enforce an
    // invariant that spans two languages.
    //
    // A static value, unlike ADMIN_API_URL, so baking it in at build time is
    // safe — that distinction is why the proxy itself lives in middleware.ts.
    proxyTimeout: 1_560_000,
  },
};

module.exports = nextConfig;
