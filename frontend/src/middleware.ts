// Proxies /admin/* to this entrance's admin API, resolved per request.
//
// This was a `rewrites()` entry in next.config.js until 2026-07-26. That does
// not work for the deployed image: `output: 'standalone'` serialises the
// resolved config into .next/required-server-files.json at build time, so
// `process.env.ADMIN_API_URL` was read during `pnpm build` — where it is
// unset — and the fallback was baked in. Both frontends shipped pointing at
// http://localhost:8001, which inside the container is the container itself,
// so every admin call failed with ECONNREFUSED while `docker inspect` showed
// the correct value in the environment. Middleware runs per request, which is
// what makes one image serve two entrances that need different destinations.
//
// The /admin prefix is preserved: the admin routers are mounted under /admin,
// and stripping it here would 404 every call. Same-origin is the point of
// proxying at all — the session cookie and the Tailscale identity header must
// behave exactly as they would against the backend directly. See
// docs/architecture/frontend.md section 1.

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  // Read inside the handler, not at module scope: module-scope access is the
  // shape a bundler can constant-fold, which is the failure this file exists
  // to fix.
  const base = process.env.ADMIN_API_URL;

  if (!base) {
    // Fail closed and say so. The alternative is a default that looks like it
    // works and silently points somewhere wrong, which is what shipped.
    console.error(
      'ADMIN_API_URL is not set; refusing to proxy /admin. ' +
        'Set it on the frontend service (see docker-compose.yml).',
    );
    return new NextResponse('admin API not configured', { status: 500 });
  }

  const destination = new URL(request.nextUrl.pathname + request.nextUrl.search, base);
  return NextResponse.rewrite(destination);
}

export const config = {
  matcher: '/admin/:path*',
};
