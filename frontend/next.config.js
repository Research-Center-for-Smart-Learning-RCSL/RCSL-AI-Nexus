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

const nextConfig = {
  ...(STANDALONE ? { output: 'standalone' } : {}),
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
    // Sized above the backend's own GENERATION_DEADLINE_SECONDS, so the
    // guardrail that fires is the one that can report a reason: this timeout
    // resets the socket and says nothing, while the backend's deadline ends
    // the stream with finish_reason=length. **Raise this whenever that one
    // rises.** It went 600s→900s, so this went 660s→960s; if it had not, the
    // silent cut would simply have moved from 30 seconds to 11 minutes.
    //
    // A static value, unlike ADMIN_API_URL, so baking it in at build time is
    // safe — that distinction is why the proxy itself lives in middleware.ts.
    proxyTimeout: 960_000,
  },
};

module.exports = nextConfig;
