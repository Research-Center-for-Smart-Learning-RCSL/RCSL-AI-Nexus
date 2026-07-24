# Deployment Topology

Extends [../ARCHITECTURE.md](../ARCHITECTURE.md) and [security.md](./security.md). Describes which machine runs what, how traffic arrives, and what other people have to do.

## 1. Physical Components

| Role | Machine | Notes |
|---|---|---|
| Compute host | Mac Studio | Runs all containers, plus the model runtimes natively. **No public IP**, tailnet only |
| Public entrance | `140.122.250.55` (NTNU) | openresty reverse proxy only. **Runs none of this project's services and stores none of its data** |
| Client devices | Laptops, phones | With Tailscale, over the tailnet; without it, through the public entrance |

The proxy host is maintained by another administrator. This project asks only that it join the tailnet and forward two hostnames.

**Model runtimes are not containers.** Ollama and MLX run natively on macOS under launchd, bound to `127.0.0.1`, because Docker on macOS cannot reach the GPU. Containers connect through `host.docker.internal:11434`. Rationale in [../ARCHITECTURE.md](../ARCHITECTURE.md) §0.1; host-level hardening in [security.md](./security.md) §7.1(d).

## 2. Domains

DNS is hosted at **Gandi**, and a wildcard record already exists:

```
*.rcsl.online.  A  140.122.250.55
```

So `ai.nexus.rcsl.online` and `api.nexus.rcsl.online` already resolve without any DNS change; only openresty server blocks are needed.

| Hostname | Purpose | Plane |
|---|---|---|
| `ai.nexus.rcsl.online` | Management UI, public entrance | Control |
| `api.nexus.rcsl.online` | Gateway inference API | Data |
| `<mac-studio>.<tailnet>.ts.net` | Management UI, tailnet entrance | Control |

Two hostnames rather than one is deliberate: nginx can apply different access rules, rate limits, and logging to each, and the data plane can later move without disturbing the management UI.

**Wildcard caveat.** Multi-label synthesis from `*.rcsl.online` works, but only while no `nexus.rcsl.online` node exists in the zone. If anyone later adds one, both hostnames stop resolving. Request explicit A records for the two names, or a dedicated `*.nexus.rcsl.online` wildcard. See [security.md](./security.md) §15.4.

## 3. Traffic Paths

```
Control plane, entrance 1 (tailnet, everyday use)
  browser --tailnet--> tailscale serve --> 127.0.0.1:3000 --> frontend-tailnet
                                                                  |  /admin/* rewrite
                                                                  v
                                                             admin-tailnet:8001
                                                    trusts Tailscale-User-Login, no password

Control plane, entrance 2 (public, for people without Tailscale)
  browser --public--> openresty --tailnet--> TAILNET_IP:3001 --> frontend-public
       ai.nexus.rcsl.online                                          |  /admin/* rewrite
                                                                     v
                                                                admin-public:8002
                                                    OIDC session; strips every Tailscale-* header

Data plane
  external service --public--> openresty --tailnet--> TAILNET_IP:8000 --> gateway
        api.nexus.rcsl.online                                              API key auth
```

API calls are same-origin through the Next.js rewrite, which avoids CORS and third-party cookie problems entirely. See [frontend.md](./frontend.md) §1.

## 4. The Critical Design Point: Separate Services, Not One Service With Two Ports

This is the easiest thing in the deployment to get wrong, and the most dangerous.

The two management entrances have **entirely different trust models**:

- Tailnet: `tailscale serve` injects `Tailscale-User-Login`, a trustworthy identity source.
- Public: requests come from anyone, and identity must be proven by OIDC.

If both shared one listening socket, **anyone on the internet could send a forged `Tailscale-User-Login: admin@example.com` and bypass OIDC entirely.**

An earlier draft attempted this with a single container publishing two ports:

```yaml
# Broken. Do not use.
command: ["uvicorn", "app.infrastructure.main_admin:app", "--port", "8001"]
ports:
  - "127.0.0.1:8001:8001"
  - "100.x.x.x:8002:8002"      # nothing is listening on 8002
```

That fails three ways: one uvicorn process listens on one port, so 8002 forwards to nothing; one process cannot mount two different middleware stacks; and uvicorn defaults to binding `127.0.0.1` inside the container, so even 8001 would not receive forwarded traffic.

The correct shape is **two services from one image**:

```yaml
services:
  admin-tailnet:
    image: rcsl-ai-nexus:latest
    command: ["uvicorn", "app.infrastructure.main_admin_tailnet:app",
              "--host", "0.0.0.0", "--port", "8001"]
    ports:
      - "127.0.0.1:8001:8001"
    networks: [app, data]
    depends_on:
      migrate: { condition: service_completed_successfully }

  admin-public:
    image: rcsl-ai-nexus:latest
    command: ["uvicorn", "app.infrastructure.main_admin_public:app",
              "--host", "0.0.0.0", "--port", "8002"]
    ports:
      - "${TAILNET_IP}:8002:8002"
    networks: [app, data]
    depends_on:
      migrate: { condition: service_completed_successfully }
```

`--host 0.0.0.0` here is correct and does not contradict [security.md](./security.md) §3.3. That rule governs the **host side** of a published port (the left of the colon). Inside a container, binding all interfaces is required for the published port to reach the process. The two are frequently conflated.

## 5. What the Proxy Administrator Needs to Do

Four items, none large:

1. **Install Tailscale and join the tailnet**, tagged `tag:ntnu-proxy` so the ACL can restrict it to the three ports it needs ([security.md](./security.md) §3.4).
2. **Add two nginx server blocks** (below).
3. **Issue Let's Encrypt certificates.** Port 80 is already open, so HTTP-01 validation works directly.
4. **Confirm nginx does not log request bodies** and that no Lua script intercepts these paths. Bodies are not logged by default; this is a confirmation, not a change.

### nginx configuration

```nginx
# Redirect plain HTTP for both hostnames, leaving the ACME path reachable
server {
    listen 80;
    server_name ai.nexus.rcsl.online api.nexus.rcsl.online;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

# Management UI
server {
    listen 443 ssl;
    http2 on;
    server_name ai.nexus.rcsl.online;

    ssl_certificate     /etc/letsencrypt/live/ai.nexus.rcsl.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ai.nexus.rcsl.online/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;

    client_max_body_size 64m;          # knowledge base uploads (Phase 2)

    limit_req zone=admin_login burst=10 nodelay;

    location / {
        proxy_pass http://TAILNET_IP:3001;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Nexus-Proxy     "<shared-secret>";

        # Identity headers may only originate from tailscale serve.
        # The application strips them too; this is the outer layer.
        proxy_set_header Tailscale-User-Login "";
        proxy_set_header Tailscale-User-Name  "";

        # The admin chat endpoint streams
        proxy_buffering    off;
        proxy_read_timeout 300s;
        proxy_http_version 1.1;
    }
}

# Inference API
server {
    listen 443 ssl;
    http2 on;
    server_name api.nexus.rcsl.online;

    ssl_certificate     /etc/letsencrypt/live/api.nexus.rcsl.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.nexus.rcsl.online/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;

    client_max_body_size 10m;

    location / {
        proxy_pass http://TAILNET_IP:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Nexus-Proxy     "<shared-secret>";

        proxy_set_header Tailscale-User-Login "";
        proxy_set_header Tailscale-User-Name  "";

        # Required for SSE. Without these, streamed output is buffered until
        # the response completes and appears to users as "the model is slow".
        proxy_buffering    off;
        proxy_read_timeout 300s;
        proxy_http_version 1.1;
    }
}
```

`proxy_buffering off` and `proxy_read_timeout` must be communicated explicitly. Without them, streaming output is withheld until generation finishes, which presents as a slow model and wastes considerable debugging time on the wrong layer.

## 6. What Is Lost Without a CDN, and Who Covers It

| Previously from a CDN | Now |
|---|---|
| Country filter | **In the application**, MaxMind GeoLite2, on both the gateway and the public admin entrance |
| Rate limiting | Per-key limits in the application, plus `limit_req` at nginx |
| DDoS mitigation | None. Campus network only |
| WAF | None. Application input validation only |
| Origin IP concealment | Already achieved; only the NTNU host is exposed |

**Therefore [security.md](./security.md) §4.3 resource guardrails are promoted from recommended to the only line of defence.** Every request now reaches the Mac Studio. Without a concurrency cap, a `max_tokens` ceiling, timeouts, and disconnect cancellation, a single abusive caller can make the machine unresponsive.

## 7. Resolving the Real Client Address

Behind the proxy, the true source is in `X-Forwarded-For`. The obvious implementation does not work here, and getting this wrong disables both the country filter and per-key CIDR allowlists.

**Why peer-IP comparison fails.** A natural approach is to check that the connecting peer is the proxy's tailnet address. Under Docker this never matches: traffic arriving through a published port is NAT'd, so the container observes the bridge gateway address (`192.168.65.x` or `172.x.0.1`), never `100.x.x.x`. The same problem breaks a naive "must come from `127.0.0.1`" check on the tailnet entrance. Both would fail closed on every request.

**What actually establishes trust** is the combination of socket binding and the tailnet ACL:

- The gateway publishes only on `${TAILNET_IP}:8000`, so it is unreachable from the LAN or the internet.
- The ACL permits only `tag:ntnu-proxy` to reach that port ([security.md](./security.md) §3.4), so no other tailnet member can connect either.
- Therefore anything arriving at the gateway process came through openresty.

A shared secret header is added as a second, independent layer, since the ACL is otherwise the sole control:

```python
# interfaces/http/middleware/client_ip.py
def resolve_client_ip(request: Request, settings: Settings) -> IPv4Address | IPv6Address:
    """Establish the caller address behind the reverse proxy.

    Trust does not come from the peer address: Docker NAT rewrites it. It comes
    from socket binding (tailnet-only publish) plus the tailnet ACL, with this
    shared-secret header as an independent second check.
    """
    if not compare_digest(request.headers.get("X-Nexus-Proxy", ""), settings.proxy_secret):
        raise UntrustedProxyError()

    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        raise UntrustedProxyError()          # never silently fall back to the peer address
    return ip_address(forwarded.split(",")[0].strip())
```

**This depends on nginx overwriting, not appending.** §5 uses `proxy_set_header X-Forwarded-For $remote_addr`, which replaces the header, so the first value is the real client. The conventional `$proxy_add_x_forwarded_for` **appends** to whatever the client sent, and a caller can then prepend arbitrary values. If the proxy configuration is ever changed to the conventional form, this parser must change to read the **last** value instead. The coupling is easy to break by tidying the nginx config, so it is recorded in both places.

## 8. Migration Path

The topology is deliberately reversible:

- Moving `rcsl.online` DNS to Cloudflare later means pointing `api.nexus` at a Tunnel. No application code changes, and traffic no longer transits a third party, resolving [security.md](./security.md) §15.1.
- Adding a second compute node leaves the entrance unchanged; only the gateway's routing targets grow.
- Dropping the dependency on the proxy host means disabling the public admin entrance; the tailnet entrance is unaffected.

## 9. Build, Deploy, and Upgrade

**Images are built on the Mac Studio.** The development machine is Windows on x86 and the target is arm64, so `docker compose build` runs on the target host. This avoids operating a registry and cross-platform builds for a single-node deployment. If a second node is added later, publishing arm64 images to GHCR becomes worthwhile.

**Migrations run as a one-shot service**, never from an application entrypoint, because three containers start from the same image and would otherwise race:

```yaml
migrate:
  image: rcsl-ai-nexus:latest
  command: ["alembic", "upgrade", "head"]
  networks: [data]
  restart: "no"
```

Every application service declares `depends_on: { migrate: { condition: service_completed_successfully } }`.

**Routine upgrade**

```bash
git pull
docker compose build
docker compose up -d          # migrate runs first, then services restart
docker compose ps             # confirm migrate exited 0 and services are healthy
```

**Rollback.** Check out the previous tag and rebuild. Alembic downgrades are written only where a migration is genuinely reversible; otherwise recovery is a database restore, which is why §9.4 of [security.md](./security.md) insists restores are rehearsed.

**Startup ordering caveat.** `${TAILNET_IP}` must exist before Docker binds to it. If the Mac reboots and Docker starts before Tailscale has an address, those services fail to bind. Use `restart: unless-stopped` so they recover once the interface appears, and confirm the behaviour after an unplanned reboot rather than assuming it.

## 10. Configuration and Secrets

Non-secret values are environment variables; secrets are mounted files read through `secrets_dir` ([backend.md](./backend.md) §8).

**Environment**

| Variable | Example | Notes |
|---|---|---|
| `ENV` | `production` | `development` locally |
| `AUTH_MODE` | `tailnet` / `oidc` / `dev` | `dev` refuses to start when `ENV=production` |
| `TAILNET_IP` | `100.x.y.z` | Used for host-side port binding |
| `PROXY_HOSTNAME` | `api.nexus.rcsl.online` | |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Password comes from a secret |
| `REDIS_URL` | `redis://redis:6379/0` | |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Runtime on the host |
| `ADMIN_API_URL` | `http://admin-tailnet:8001` | Per frontend container |
| `OIDC_ISSUER` | provider dependent | |
| `OIDC_CLIENT_ID` | | |
| `ALLOWED_COUNTRIES` | `TW,AU` | |
| `GEOIP_DB_PATH` | `/data/GeoLite2-Country.mmdb` | Refreshed monthly |
| `BOOTSTRAP_ADMIN_LOGIN` | `you@example.com` | Inert once any user exists |
| `MAX_CONCURRENT_INFERENCE` | `2` | Tune to model size |
| `MAX_TOKENS_CEILING` | `4096` | |
| `REQUEST_TIMEOUT_SECONDS` | `300` | |

**Secrets** (`/run/secrets`, never environment variables)

| Secret | Purpose |
|---|---|
| `postgres_password_gateway` | Read-only gateway account |
| `postgres_password_admin` | Read-write admin account |
| `postgres_password_migrate` | DDL account |
| `api_key_pepper` | HMAC pepper, supports two values during rotation |
| `oidc_client_secret` | |
| `proxy_shared_secret` | Matches `X-Nexus-Proxy` in nginx |
| `redis_password`, `qdrant_api_key`, `minio_root_password` | |

`.env.example` lists every field name with no values.

## 11. Local Development

The Windows development machine has no `tailscale serve`, no openresty, no OIDC provider, and no GeoLite2 database. Taken literally, the middleware described here rejects every request and nothing runs locally.

```bash
ENV=development
AUTH_MODE=dev
```

This injects a fixed admin `Actor`, and disables the country filter and the trusted-proxy check. Ollama can run natively on Windows with `OLLAMA_BASE_URL=http://host.docker.internal:11434`, exactly as in production.

**`AUTH_MODE=dev` combined with `ENV=production` is a startup failure**, not a warning. A misconfigured deployment refuses to boot rather than quietly serving an unauthenticated admin API. [security.md](./security.md) §14 carries a matching pre-launch check, and it is worth testing rather than assuming.

Not reproducible locally, and therefore only verifiable on the Mac Studio: GPU-backed inference, the tailnet entrance, the OIDC flow, and nginx behaviour.
