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
};

module.exports = nextConfig;
