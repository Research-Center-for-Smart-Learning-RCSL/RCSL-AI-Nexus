# Management UI

The Next.js application behind both admin entrances. One image is built from
this directory and run twice — `frontend-tailnet` and `frontend-public` —
differing only in the `ADMIN_API_URL` that `src/middleware.ts` rewrites
`/admin/*` to. The design is in
[`../docs/architecture/frontend.md`](../docs/architecture/frontend.md); the
stack as a whole is in [`../README.md`](../README.md).

## Development

Node 22 and pnpm. The lockfile is `pnpm-lock.yaml`, and a second package manager
writes a second one.

```bash
pnpm install
pnpm dev                # http://localhost:3000
```

`ADMIN_API_URL` must name a reachable admin entrance. Without it the middleware
refuses to proxy `/admin` rather than falling back to a default.

## Gates

```bash
pnpm lint
pnpm test               # vitest
pnpm build              # the production build CI also runs
pnpm test:e2e           # Playwright against a deterministic admin fixture
pnpm test:e2e:full      # Playwright against the real admin app and Postgres
pnpm gen:api            # regenerate src/lib/generated/admin-api.ts
```

## Layout

```
src/app/(auth)          sign-in and invitation acceptance
src/app/(dashboard)     one route per management screen
src/features/<screen>   api, schema, hooks and components for one screen
src/components/ui       primitives on Base UI, copied in rather than installed
src/components/composed the skeleton every screen builds on
src/lib                 api client, session context, generated types
```

`src/lib/generated/` is committed rather than built, because the image builds
from this directory alone and a type derived from the backend cannot be build
output here. `src/lib/api-contract.ts` checks each hand-written zod schema
against it, so a renamed or retyped field fails `tsc` rather than a browser.

## Deployment

The image is built by `docker-compose.yml` at the repository root and served
behind openresty. Nothing here deploys to Vercel.
