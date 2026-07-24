# RCSL AI Nexus

A self-hosted LLM gateway and management platform. Runs on a Mac Studio
treated as a 24/7 AI server rather than a personal computer.

Design documentation lives in [`docs/`](./docs). Start with
[`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md); the decisions and their
reasoning are recorded there rather than here.

[`docs/PROGRESS.md`](./docs/PROGRESS.md) is the running record of what has
actually been built and what was learned building it. Read that first if you
want the current state rather than the design.

## Layout

```
backend/      FastAPI, hexagonal architecture. One image, three ASGI apps
frontend/     Next.js management UI, one instance per admin entrance
docs/         Architecture, security, deployment
```

## Local development

The development machine does not need to be the Mac Studio. Requirements:
Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm, and
Docker.

```bash
cp .env.example .env          # placeholders are fine locally
cd backend && uv sync
uv run pytest                 # unit tests only; integration tests skip
```

Integration tests need a database and are skipped unless `TEST_DATABASE_URL`
is set. The variable is deliberately not `DATABASE_URL`, so running the unit
suite can never reach a real database by accident.

```bash
docker run --rm -d --name nexus-pg-tmp -p 127.0.0.1:15432:5432 \
  -e POSTGRES_USER=nexus -e POSTGRES_PASSWORD=devpw -e POSTGRES_DB=nexus \
  postgres:17-alpine

TEST_DATABASE_URL=postgresql+asyncpg://nexus:devpw@127.0.0.1:15432/nexus uv run pytest
```

These tests drop and recreate the schema on every run, which is why they must
never be pointed at anything you care about.

`AUTH_MODE=dev` disables the trusted-proxy check and resolves the caller to the
peer address, which is what lets the stack run without `tailscale serve` and
openresty in front of it. It does **not** inject an admin identity; the gateway
still requires a real API key locally. It is a **startup failure** when
combined with `ENV=production`, so a misconfigured deployment refuses to boot
rather than quietly weakening the perimeter.

What cannot be reproduced locally, and is therefore only verifiable on the
Mac Studio: GPU-backed inference, the tailnet entrance, and nginx behaviour.
The local credential flow (invitation, password, TOTP) depends on nothing
external and does run locally.

## Running the stack

```bash
docker compose build
docker compose up -d
docker compose ps             # migrate should have exited 0
```

Model runtimes are deliberately **not** in Compose. Containers on macOS
cannot reach the GPU, so a containerised Ollama would be CPU-only and MLX
would not run at all. Install them natively on the host, bound to
`127.0.0.1`, and containers reach them through `host.docker.internal`.
See [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) section 0.1.

## Two things that look like mistakes and are not

**Every published port binds to `127.0.0.1` or the tailnet address, never
`0.0.0.0`.** On Docker Desktop a bare `"5432:5432"` publishes to every host
interface, putting the database on the LAN. Inside the containers uvicorn
still binds `0.0.0.0`; the rule is about the host side of the mapping only.

**The two admin entrances are separate services, not two ports on one.**
The tailnet entrance trusts a `Tailscale-User-Login` header outright. If the
public entrance shared that socket, a forged header from the internet would
grant administrator access. Isolation comes from socket binding, not from
string comparison.

## Before exposing anything publicly

[`docs/architecture/security.md`](./docs/architecture/security.md) section 14
is a pre-launch checklist. Section 15 records the risks that were accepted
deliberately, and what should trigger reconsidering them.

## License

Copyright (C) 2026 Research Center for Smart Learning (RCSL), National Taiwan
Normal University, and contributors.

Licensed under the **GNU Affero General Public License v3.0**. See
[`LICENSE`](./LICENSE) for the full text.

One clause deserves attention because this project's architecture triggers it
directly. AGPL section 13 treats **network interaction as distribution**: where
the GPL obliges you to release source only when you hand someone a copy, the
AGPL obliges you to offer source to anyone who merely uses your modified
version over a network.

This platform exposes both a public inference API and a public management UI,
which is precisely the scenario that clause was written for. In practice, if
you deploy a modified version, everyone reaching those endpoints is entitled to
the corresponding source. The straightforward way to satisfy that is to publish
your fork and link to it from the running instance rather than treating it as
something to handle on request.
