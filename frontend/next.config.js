/** @type {import('next').NextConfig} */

// Every API call must be same-origin so that the session cookie and the
// Tailscale identity header behave identically to a direct backend call:
// no CORS, no third-party cookie restrictions, no per-entrance API hostname.
// See docs/architecture/frontend.md section 1.
const ADMIN_API_URL = process.env.ADMIN_API_URL ?? 'http://localhost:8001';

// Standalone output is what the Dockerfile ships, but producing it requires
// creating symlinks, which Windows refuses without Developer Mode. Gating it
// on an env var keeps `pnpm build` usable on the development machine while
// the image build (on macOS) still gets a self-contained bundle.
const STANDALONE = process.env.NEXT_OUTPUT === 'standalone';

const nextConfig = {
  ...(STANDALONE ? { output: 'standalone' } : {}),
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: '/admin/:path*', destination: `${ADMIN_API_URL}/admin/:path*` },
    ];
  },
};

module.exports = nextConfig;
