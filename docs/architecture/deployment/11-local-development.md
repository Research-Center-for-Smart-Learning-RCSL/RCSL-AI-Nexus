# 11. Local Development

[← Deployment Architecture](../deployment.md)

The Windows development machine has no `tailscale serve`, no openresty, and no GeoLite2 database. Taken literally, the middleware described here rejects every request and nothing runs locally.

Copy `.env.example` to `.env`, set the two values below, and bring the stack up
the same way production does — there is no second compose file:

```bash
cp .env.example .env        # then set:
#   ENV=development
#   AUTH_MODE=dev
docker compose up -d        # migrate runs first, then the services
docker compose logs -f gateway
```

The backend test suites are `pytest tests/unit` (no Docker) and
`pytest tests/integration` (needs the Compose Postgres); the frontend's are
`pnpm vitest run` and `pnpm playwright test`, from `frontend/`.

`AUTH_MODE=dev` disables the country filter and the trusted-proxy check, and substitutes `DEV_TAILNET_LOGIN` for the Tailscale identity header the tailnet entrance would otherwise read. It does **not** inject a fixed admin `Actor` — see [backend.md](../backend.md) §10 — and the gateway still requires a real API key. Ollama can run natively on Windows with `OLLAMA_BASE_URL=http://host.docker.internal:11434`, exactly as in production.

**`AUTH_MODE=dev` combined with `ENV=production` is a startup failure**, not a warning. A misconfigured deployment refuses to boot rather than quietly serving an unauthenticated admin API. [security.md](../security.md) §14 carries a matching pre-launch check, and it is worth testing rather than assuming.

The local credential flow (invitation, password, TOTP) **is** reproducible locally, since it depends on nothing external. Run with `AUTH_MODE=local` to exercise it.

Not reproducible locally, and therefore only verifiable on the Mac Studio: GPU-backed inference, the tailnet entrance, and nginx behaviour.
