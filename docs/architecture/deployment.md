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

**They are not the only native processes, and the third is easy to forget because it is not a runtime.** `launchd/host-metrics.py` serves free memory, disk, uptime and load on `127.0.0.1:9101` for the host status card, and it exists for the same reason as the two above: a container on macOS reads the Linux VM's memory and the VM's disk, and those numbers are plausible and wrong. Anything that enumerates what runs on the host — the health daemon's checks, the LaunchDaemon install list in the first-deploy runbook — has to count three, not two.

**Observability runs as two containers.** Prometheus scrapes the three applications' `/metrics` and Grafana reads Prometheus. Prometheus is on internal-only networks and publishes no host port. Grafana binds `127.0.0.1:3002`, exposed to the tailnet through `tailscale serve --https 8443` for operators, and therefore cannot be internal-only: Docker will not publish a host port into an `internal` network, so Grafana carries a dedicated non-internal `viz-ingress` alongside its internal link to Prometheus (§6 of security.md explains the trade and why Prometheus is deliberately not given the same). Neither is reachable from the public entrance. See [security.md](./security.md) §6.

## 2. Domains

DNS is hosted at **Gandi**, and a wildcard record already exists:

```
*.rcsl.online.  A  140.122.250.55
```

So `llm.rcsl.online` and `llmapi.rcsl.online` already resolve without any DNS change; only openresty server blocks are needed.

| Hostname | Purpose | Plane |
|---|---|---|
| `llm.rcsl.online` | Management UI, public entrance | Control |
| `llmapi.rcsl.online` | Gateway inference API | Data |
| `<mac-studio>.<tailnet>.ts.net` | Management UI, tailnet entrance | Control |

Two hostnames rather than one is deliberate: nginx can apply different access rules, rate limits, and logging to each, and the data plane can later move without disturbing the management UI. It also keeps the session cookie's origin off the data plane — one hostname serving both would put the management session on the same origin as a public, key-authenticated inference API, and collide the two applications' `/healthz` and `/metrics`.

**Both names are single-label, and that is the reason for them.** These replaced `ai.nexus.rcsl.online` and `api.nexus.rcsl.online` on 2026-08-04. A DNS wildcard matches any depth but a **TLS** wildcard matches exactly one label, so the two-label names resolved long before `*.rcsl.online` could serve them and needed certificates of their own ([ROADMAP.md](../ROADMAP.md)). `llm` and `llmapi` are covered by the existing wildcard on both sides, and they no longer depend on nobody ever creating a `nexus.rcsl.online` node in the zone — which was the fragility recorded in [security.md](./security.md) §15.4. `llmapi` is one word rather than `api.llm.rcsl.online` for exactly this reason: a dot there would put the name back outside the wildcard certificate and reintroduce the dependency on the zone's shape.

What remains of §15.4 applies to any name here: the wildcard resolves *every* subdomain to the proxy host, so anyone able to obtain a vhost there can serve content under a plausible name. Explicit A records would close that; the wildcard predates this project and the domain is maintained by someone else.

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
       llm.rcsl.online                                          |  /admin/* rewrite
                                                                     v
                                                                admin-public:8002
                                          password + TOTP session; strips every Tailscale-* header

Data plane
  external service --public--> openresty --tailnet--> TAILNET_IP:8000 --> gateway
        llmapi.rcsl.online                                              API key auth
```

API calls are same-origin through the Next.js rewrite, which avoids CORS and third-party cookie problems entirely. See [frontend.md](./frontend.md) §1.

## 4. The Critical Design Point: Separate Services, Not One Service With Two Ports

This is the easiest thing in the deployment to get wrong, and the most dangerous.

The two management entrances have **entirely different trust models**:

- Tailnet: `tailscale serve` injects `Tailscale-User-Login`, a trustworthy identity source.
- Public: requests come from anyone, and identity must be proven by password plus TOTP.

If both shared one listening socket, **anyone on the internet could send a forged `Tailscale-User-Login: admin@example.com` and bypass the password and TOTP entirely.**

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
    networks: [control-tailnet, admin-data]
    depends_on:
      migrate: { condition: service_completed_successfully }

  admin-public:
    image: rcsl-ai-nexus:latest
    command: ["uvicorn", "app.infrastructure.main_admin_public:app",
              "--host", "0.0.0.0", "--port", "8002"]
    ports:
      - "${TAILNET_IP}:8002:8002"
    networks: [control-public, admin-data]
    depends_on:
      migrate: { condition: service_completed_successfully }
```

The network names are not incidental: the admin entrances sit on the control
plane's segments and never on the gateway's, which is what stops a compromised
data plane from forging an administrator identity to the tailnet entrance. See
[security.md](./security.md) §3.2.

`--host 0.0.0.0` here is correct and does not contradict [security.md](./security.md) §3.3. That rule governs the **host side** of a published port (the left of the colon). Inside a container, binding all interfaces is required for the published port to reach the process. The two are frequently conflated.

## 5. What the Proxy Administrator Needs to Do

Four items, none large:

1. **Install Tailscale and join the tailnet**, tagged `tag:ntnu-proxy` so the ACL can restrict it to the three ports it needs ([security.md](./security.md) §3.4).
2. **Add two nginx server blocks** (below).
3. **Serve a certificate for each name.** Both are single-label, so an existing `*.rcsl.online` wildcard covers them and no issuance may be needed at all — point the server blocks at it. This is new since the rename: the previous two-label names were outside a TLS wildcard's one-label match and each needed its own certificate. If there is no usable wildcard, issue per-name certificates; port 80 is already open, so HTTP-01 validation works directly.
4. **Confirm nginx does not log request bodies** and that no Lua script intercepts these paths. Bodies are not logged by default; this is a confirmation, not a change.

### The one way this goes wrong, found on the first real attempt

**Every `proxy_set_header` below must end up inside the `location` block that actually serves the request.** nginx inherits them all-or-nothing: a level inherits the set from above *only if it declares none of its own*, so a single `proxy_set_header` in a `location` silently discards every one inherited from the `server` block. There is no warning, `nginx -t` passes, and the configuration file reads exactly as intended.

This is not hypothetical. On 2026-08-03 the administrator entered the directives into Nginx Proxy Manager's **Custom Nginx Configuration** field, which is inserted at *server* level, while NPM's generated `location /` carries its own `proxy_set_header` set — so all four of ours were dropped. Both header controls failed at once and nothing upstream showed it: `client_max_body_size`, `proxy_buffering` and `proxy_read_timeout` are not `proxy_set_header` and inherit normally, so everything else behaved. See [PROGRESS.md](../PROGRESS.md) 2026-08-03.

Three consequences worth carrying:

- **Verify with `nginx -T`, not the file or the UI.** It prints the configuration nginx actually loaded. The check is whether the lines appear *inside* `location`, not whether they appear.
- **A hand-written `location` must re-declare what the generated one had.** The same rule applies in reverse: such a block discards the proxy's own `Host`, `X-Forwarded-Proto`, `Upgrade` and `Connection`. Copy them out of `nginx -T` rather than from memory. This platform reads neither `Host` nor `X-Forwarded-Proto`, so those two cost nothing here, but `Upgrade`/`Connection` are what a websocket support toggle exists to set.
- **`X-Forwarded-For` is replaced, never added alongside.** nginx does not de-duplicate `proxy_set_header`; declaring it twice sends the header twice, and `client_ip.py` reads the *first* value, so leaving the proxy's own `$proxy_add_x_forwarded_for` next to ours restores the defect it was written to fix.

`scripts/verify-public-entrance.sh` tests all of this from outside and distinguishes "no header set" from "wrong value set", which look identical from a single probe.

### nginx configuration

```nginx
# http level. The zone the management block's limit_req names below; without
# it nginx refuses to load the configuration with "unknown limit_req zone".
# Referenced here since this section was written and defined nowhere until
# 2026-08-03, so the template as published could not start.
limit_req_zone $binary_remote_addr zone=admin_login:10m rate=10r/m;

# Redirect plain HTTP for both hostnames, leaving the ACME path reachable
server {
    listen 80;
    server_name llm.rcsl.online llmapi.rcsl.online;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

# Management UI
server {
    listen 443 ssl;
    http2 on;
    server_name llm.rcsl.online;

    # Per-name paths shown for concreteness. A `*.rcsl.online` wildcard covers
    # this name — both are single-label — so pointing both blocks at the
    # wildcard is equally correct and is one fewer renewal to forget.
    ssl_certificate     /etc/letsencrypt/live/llm.rcsl.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/llm.rcsl.online/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;

    # Knowledge base uploads. Deliberately *looser* than the application's own
    # 32 MiB (`domain/services/upload_policy.py`), so ours is the limit that
    # fires and the caller gets an error naming the reason. Set it tighter and
    # nginx rejects the request itself, with its own HTML 413 in place of the
    # upload dialog's message. Entered as 10m on the first attempt.
    client_max_body_size 64m;

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
        proxy_read_timeout 3600s;
        proxy_http_version 1.1;
    }
}

# Inference API
server {
    listen 443 ssl;
    http2 on;
    server_name llmapi.rcsl.online;

    ssl_certificate     /etc/letsencrypt/live/llmapi.rcsl.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/llmapi.rcsl.online/privkey.pem;
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
        #
        # `3600s` is the target; the machine currently runs `86400s` on both
        # hosts (confirmed by `nginx -T`, 2026-08-09) and nothing is waiting on
        # the difference. Stated here because a template that silently disagrees
        # with the deployment is how `300s` survived in ROADMAP.md for two days
        # after the real value had been read.
        proxy_buffering    off;
        proxy_read_timeout 3600s;
        proxy_http_version 1.1;
    }
}
```

`proxy_buffering off` and `proxy_read_timeout` must be communicated explicitly. Without them, streaming output is withheld until generation finishes, which presents as a slow model and wastes considerable debugging time on the wrong layer.

**`proxy_read_timeout` was `300s` here until 2026-08-07, and that number became wrong without anyone touching it.** It bounds the gap between reads, and **prompt evaluation produces no bytes at all** — so the longest legitimate silence is a full context being read. `config.py` put that at `98304 / 105.5 = 932` seconds against the platform's own 1200-second per-read ceiling (`65536 / 117.9 = 556` against 600 until 2026-08-14); on the ceiling and the model in force today it is `122880 / 711 = 173` seconds, because 105.5 tok/s was the dense model's and that model now serves nothing (re-measured 2026-08-17 — see the `MAX_CONTEXT_LENGTH` row in §10). Every figure in the next three paragraphs is the 2026-08-14 one it was written against, and is kept because the reasoning is what they are here for. `300s` cut the 556 in force that day roughly in half, and the cut arrives as a reset with nothing in any application log, which is the failure mode this whole section exists to avoid.

It was correct when written: `MAX_CONTEXT_LENGTH` was 32768, so the worst silence was 278 seconds and fit inside 300. **The ceiling doubled on 2026-08-05 and this file was not one of the places that got updated.** `config.py` already says those values "are one decision and have to be changed together" and names two readers; nginx is the third, and it is the one nobody can see from the repository.

**What is actually running is `86400s` on both hosts, confirmed by `nginx -T` on 2026-08-09.** This section did not say so until that day, and the reading is not new — `llmapi`'s value was read on 2026-08-07 and recorded in [PROGRESS.md](../PROGRESS.md); it simply never reached [ROADMAP.md](../ROADMAP.md), which went on saying `300s`. The 2026-08-09 run settled it against the running configuration rather than against either file:

| | `llm.rcsl.online` | `llmapi.rcsl.online` |
|---|---|---|
| `proxy_read_timeout` | `86400s` | `86400s` |
| `proxy_buffering` | `off` | `off` |
| `client_max_body_size` | `64m` — matches this section | `512m` — this section says `10m` |
| defined in | `data/nginx/custom/http.conf` | `data/nginx/custom/http.conf` |

**Three things that were open closed with the same command.** `proxy_buffering off` is confirmed live on both hosts for the first time. `server_name llmapi.rcsl.online` appears exactly once and `nginx -t` reports no `conflicting server name`, so the duplicate-block repair of 2026-08-07 holds and has not regressed — previously unverifiable from outside. And **the management host's directives had never been read at all**; they are now known rather than assumed, which was the last place in this section where a value was being taken on trust. The timeout defect this section spent three paragraphs deriving **was real against the specification and had never once been real in the deployment** — the same duplicate-server-block story as the headers, one file further on. Read the derivation above as the reasoning for a target, not as a description of a fault.

**The remaining case is for lowering it, and it is weak on purpose.** A day is generous to the point of not being a backstop: `proxy_read_timeout` is what reclaims a connection from an upstream that has genuinely hung, and nginx worker connections are finite, so an effectively unbounded value turns a hang into pinned connections. `3600s` restores that property while staying far above anything legitimate. **The comparison to make is against another between-reads bound, not against a whole-request one**: `proxy_read_timeout` limits the gap between bytes, so its counterpart is `REQUEST_TIMEOUT_SECONDS` (1200 since 2026-08-14), inside which the longest honest silence — a full `MAX_CONTEXT_LENGTH` prompt, `98304 / 105.5 = 932` seconds when this was written and `122880 / 711 = 173` on the current ceiling and model — already has to fit. **`3600s` still clears that with room, so this change needed nothing from the proxy administrator** — which is the point of having sized it against the class of bound rather than against the number. The 2100-second figure below is the sum of that and the generation deadline, which is a budget for a whole request and bounds nothing about a single gap; setting them side by side is the same conflation this section warns about two paragraphs up. **Nothing user-visible is waiting on this**, and whoever is asked should be told that; an urgent-sounding request for a change with no symptom behind it spends credibility that the next real one will need.

**A note on how the wrong number survived.** `1560s` was derived from the platform's own limits, and the 2026-08-09 revision proposed `3600s` derived instead from the model's architectural maximum — `262144 / 117.9 = 2224` seconds — on the reasoning that a bound fitted to a tunable expires whenever the tunable moves. That reasoning is worth keeping for choosing a target, with one qualification it did not carry: **2224 seconds is not a silence this deployment can currently produce**, because `MAX_CONTEXT_LENGTH` refuses a prompt that large with a `413` and `REQUEST_TIMEOUT_SECONDS` would cut the gap at 1200 anyway (600 on the day this was written; the raise landed 2026-08-14). It is the bound that survives *changing* those two, which is a different and much weaker claim than the one it was written as. What the revision did not do, and what mattered more than any of this, was check whether the value being "corrected" was the value in force. **It was not, and this repository already knew: the reading was in `PROGRESS.md` and had never been propagated to `ROADMAP.md`, which is the direction `PROGRESS.md`'s own header says to distrust.** Deriving a number more rigorously is worth nothing next to reading the one that is live.

**The management host reads `86400s` and `64m`**, the latter exactly as specified above. Its value could not have been learned from outside in any case: the frontend's own `experimental.proxyTimeout` (`next.config.js`, 2,160,000 ms — thirty-six minutes, raised with the read timeout on 2026-08-14 and 1,560,000 when this was written) sits in front of it and cuts a stalled request first, which is the inner limit firing and is correct. Reading the file was the only way, and it took one command.

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

## 8.1 Source Availability Obligation

The project is licensed under AGPL-3.0, whose section 13 treats network
interaction as distribution. Both public hostnames in section 2 are exactly
the trigger: anyone reaching `llm.rcsl.online` or
`llmapi.rcsl.online` is entitled to the source of the version being run,
including local modifications.

This is an operational obligation, not a one-time licensing formality, so it
belongs in the deployment runbook:

- Keep the deployed revision published, and link to it from the management UI
  footer rather than fielding requests individually.
- Tag or otherwise identify what is actually running, so the offered source
  corresponds to the deployed build rather than to whatever is on `main`.

## 9. Build, Deploy, and Upgrade

**Images are built on the Mac Studio.** The development machine is Windows on x86 and the target is arm64, so `docker compose build` runs on the target host. This avoids operating a registry and cross-platform builds for a single-node deployment. If a second node is added later, publishing arm64 images to GHCR becomes worthwhile.

**Migrations run as a one-shot service**, never from an application entrypoint, because five containers start from the same image — the gateway, the two admin entrances, `parser` and this job — and the three that open the database would otherwise race:

```yaml
migrate:
  image: rcsl-ai-nexus:latest
  command: ["sh", "-c", "alembic upgrade head && python -m app.infrastructure.db_roles && python -m app.infrastructure.provision"]
  networks: [admin-data]
  restart: "no"
```

Every backend service declares `depends_on: { migrate: { condition: service_completed_successfully } }`, `parser` included — it needs no schema, only the image tag to exist. The two frontends are the exception and depend on their own admin entrance instead, which reaches `migrate` transitively.

The middle step is the one this file omitted until 2026-08-18, and omitting it produces a deployment that starts and then cannot read anything: `db_roles` creates the gateway and admin accounts and their grants, connecting as the schema owner, which is the only place that account is used. It has to run after `alembic upgrade head`, because a grant needs the table to exist, and before any application starts, because those accounts are what the applications authenticate as (§6 of [security.md](./security.md)). The `provision` step after it writes the single configured compute node (there is no node-registration endpoint until the SSRF guard ships; see [security.md](./security.md) §7.2) and reconciles any model left in a transient state by a crash.

**Routine upgrade**

```bash
docker tag rcsl-ai-nexus:latest rcsl-ai-nexus:rollback-$(date +%Y%m%d)
docker tag rcsl-ai-nexus-frontend:latest rcsl-ai-nexus-frontend:rollback-$(date +%Y%m%d)

git pull
docker compose build
docker compose up -d          # migrate runs first, then services restart
docker compose ps             # confirm migrate exited 0 and services are healthy
```

After any `up -d` that recreates containers, also confirm the published ports are actually bound — see the startup-ordering note below for why `docker compose ps` does not show this.

**Deploy from a commit, not from a working tree.** The rollback path below is a git one, so an image built from uncommitted changes corresponds to nothing and can only be rolled back to whatever image tag happens to survive.

**Rollback.** Check out the previous tag and rebuild. Alembic downgrades are written only where a migration is genuinely reversible; otherwise recovery is a database restore, which is why §9.4 of [security.md](./security.md) insists restores are rehearsed.

The `rollback-YYYYMMDD` image tags above are the faster path when the rebuild itself is what has to be skipped, and the convention is that **they name the last build known to be good, not simply the previous one**. Re-tagging before every build would overwrite a good target with a bad one on exactly the deploy that is fixing something: on 2026-07-29 the second deploy of the day was replacing a build with a known wire-protocol defect, so `rollback-20260729` was deliberately left pointing at the build before *both*. A tag that means "whatever ran last" is worth nothing at the moment it is needed.

**Some changes cannot be deployed in either order.** A routing policy for a capability the running image does not know is refused by `ManageRoutingPolicies`, so the code that widens the capability set has to ship before the policy that uses it can be written. Expect a deploy followed by a configuration step rather than a single atomic change; the first-deploy runbook §7 carries the `assist` case.

**Startup ordering, and why `restart: unless-stopped` does not cover it.** `${TAILNET_IP}` must exist before Docker binds to it, and at boot it does not: Docker Desktop restored containers roughly 21 seconds in on 2026-07-26, before `tailscaled` had put the address on `utun0`, and every forward naming it failed with `listen tcp4 100.x.y.z:8000: bind: can't assign requested address`.

**What decides that race is `tailscaled`'s own startup, and it varies by more than the whole margin.** Seven boots on 2026-07-26 bracket it. Docker is the *less* variable side — 10.3 to 14 seconds from `tailscaled` starting to its first `exposer.Add`, on every boot where it bound at all — but it is not a constant, and the two boots that set the low end of that range are the two most recent.

| boot | `tailscaled` start | address usable | Docker's `exposer.Add` | margin |
|---|---|---|---|---|
| 16:45, failed | 16:45:15 | 16:45:32 (+17s) | 16:45:29 | **−3s** |
| 17:21, passed | 17:21:48 | 17:21:48 (+0s) | 17:21:59 | **+11s** |
| 18:08, passed | 18:08:14 | 18:08:23 (+9s) | 18:08:25 | **+2s** |
| 19:09, failed for another reason | 19:09:59 | 19:10:00 (+1s) | *never* | *no race* |
| 19:43, passed | 19:43:28 | 19:43:37 (+9s) | 19:43:39.7 | **+2.7s** |
| 20:24, passed | 20:24:22 | 20:24:24 (+2s, cache hit) | 20:24:32.3 | **+8.3s** |
| 20:29, passed | 20:29:06 | 20:29:15 (+9s, cache miss) | 20:29:16.4 | **+1.4s** |
| **21:02, fault injected** | 21:04:13 (held 90s) | 21:04:14 (+1s, cache hit) | 21:02:56 (**bind failed**) | **−78s** |

**The last row is not a measurement of this race; it is manufactured weather and belongs to no distribution here.** `tailscaled` did not start on its own, so its column records the release rather than the boot. The only number in it that means anything is the margin: the natural ceiling is +1.3 seconds and the injector produced −78, sixty times over. That is what the ninety-second hold buys, and the three failed binds at 21:02:56 are the receipt.

**The budget is shrinking, and it is now small enough to state exactly.** Docker's lag across the six boots where it bound: 14.0, 11.0, 11.0, 11.7, **10.3**, **10.4** seconds — the two lowest are the last two, so the earlier "stable 11 to 14" reading was the small sample talking. Meanwhile every cache-miss boot has put the address up at exactly 9 seconds, three times with no spread at all. `10.3 − 9 = 1.3s` is the whole of what protects a cache-miss boot, and 20:29 passed by 1.4.

**The fourth row is what the table cannot measure.** It records a race with only one runner: the address was up in a second and Docker never bound anything, because it never restored a container. Winning this race is necessary for a boot to succeed and nowhere near sufficient, and the three-row version of this table quietly implied otherwise.

**The variable is whether the netmap disk cache loads.** With it, the address is up in the same second `tailscaled` starts, because it needs neither the network nor the control plane — at 17:21:52 the daemon was still reporting `You are logged out ... failed to resolve controlplane.tailscale.com` with the address already on `utun0`. Without it, the address waits for control: 9 seconds on the third boot, 17 on the failing one. The cache is written when a new netmap arrives from control, and a boot that *loads* it does not rewrite it, so caches do not chain: a boot that wins by eleven seconds leaves nothing behind and hands the next one the slow path. Applying a tailnet ACL also invalidates it, since the netmap carries the packet filter. The model has now made four predictions and all four held, with the alternation holding across seven boots and no exception: 18:08:23 wrote, so 19:09 loaded (+1s); 19:09 loaded without rewriting, so 19:43 missed (+9s) and wrote at 19:43:38; 19:43 wrote, so 20:24 loaded (+2s) and logged no write in its session; 20:24 loaded without rewriting, so 20:29 missed (+9s) and wrote at 20:29:15. Load-without-rewrite now rests on three observations rather than one. By the same rule the boot after 20:29 is a fast one.

**That last prediction was never tested, and the model took its first exception instead.** At 21:00:20 `tailscaled` was restarted by hand — a rehearsal of the recovery command §1.1a documents for a SIGKILLed injector — and at 21:00:27 it came up on `netmap cache is not available`, thirty-one minutes after the 20:29:15 write that should have been sitting there for it. A time-to-live does not explain it: 18:08:23 wrote and 19:10:00 loaded sixty-one minutes later. The one clean distinction is that this was a daemon restart inside a running session rather than a boot, and every hit the model has ever recorded followed a reboot. So there are now two live possibilities with one observation each — the model is wrong, or restart and boot are not the same event for this cache — and until they are separated the alternation may only be applied to boots. The prediction for the boot after 20:29 went untested because the injector held `tailscaled` down through it; the daemon that started at 21:04:13 loaded the cache written at 21:00:30 and logged no rewrite, which makes load-without-rewrite four observations and predicts a cache miss on the next boot.

**What the model does not buy is a losing boot on demand, and 20:24/20:29 settled that it never will.** Those two were a deliberate back-to-back reboot aimed at the second one, which is the cache-miss boot. The lever worked mechanically — no cache, address at 9 seconds, margin down from 8.3s to 1.4s — and still passed. With cache-miss boots pinned at 9 seconds (three observations, zero spread) and Docker's floor at 10.3, the lever's ceiling is a 1.3-second margin; it cannot go negative. Only 16:45 lost, on a 17-second address that has not recurred in six subsequent boots.

**The zero-spread half of that is now falsified, and the alternation half is now five for five.** The 21:51 boot — §1.1b's injection, which had no reason to be about this — was predicted to miss the cache and take 9 seconds. It missed the cache, which is the fifth consecutive confirmed prediction and the point at which load-without-rewrite stops being provisional. The address took **11 seconds** (`tailscaled` at 21:51:30, `peerapi` on 100.108.250.62 at 21:51:41), so cache-miss boots measure 9, 9, 9, 11, 17 rather than a constant, and 16:45's 17 seconds is better read as the top of that distribution than as an outlier retired by later boots. Recomputing, `10.3 − 11 = −0.7`. That subtraction takes the extremes of two distributions from different boots, which is exactly the reasoning this file has been careful to avoid elsewhere, and 21:51 produced no margin observation at all because the stack was deliberately stopped and Docker bound nothing. So the defensible correction is the weaker one: **the margin distribution is wider than three samples made it look, and "rebooting cannot lose" was overstated**. The conclusion it was supporting — inject rather than reboot — is unaffected and now rests on repeatability rather than on a guarantee: a 90-second hold is six times the margin Docker needs to lose by, and a 9-to-17-second address distribution is weather. The reconcile log's "15 seconds" for the same event is its five-second sampling granularity, not a measurement; the address timings above all come from `tailscaled`'s log. 21:51:41 also wrote the cache, so the next boot is predicted to load it.

**So the repair path is exercised by injecting the fault, not by waiting for it.** `launchd/delay-tailscaled-once.sh` holds `tailscaled` down for 90 seconds at boot — six times the margin Docker needs to lose by — so Docker binds before the address exists and the reconciler has to do what it was written for. It is a test tool, deliberately absent from the runbook's install list, and it deletes its own plist as its first action so it can only ever affect one boot. Procedure and the risk it carries (the host is off the tailnet for the duration, so a person must be at the machine) are in runbook §1.1a.

**It was run on 2026-07-26 at 21:02 and the repair path walked for the first time.** Docker bound at 21:02:56, seventy-eight seconds before the address existed, and failed on exactly the three services that name it — `:8000`, `:3001`, `:8002`. The reconciler found all three dropped, recreated them, and logged `OK: all bindings restored` at 21:05:31; nine services, six matching bindings and six entrances at 200 afterwards. What that establishes is the repair working *at boot*, with Docker Desktop restoring containers and the daemon settling and the address arriving all at once — the part a hand test cannot reproduce. It does not establish that the race occurs unaided, which 16:45 already did, and it says nothing about the container bring-up path, which this injector cannot reach because it holds back the address rather than the daemon's restore.

**That second path has an injector of its own, and it is much cheaper.** `launchd/stop-stack-once.sh` (runbook §1.1b) stops the stack and leaves the reboot to a person; `restart: unless-stopped` then does the work, because the "unless" means a container that was explicitly stopped is not restored when the daemon returns. The reconciler wakes to precisely the state the 19:09 boot left it — everything present, nothing running — and has to bring the platform up with everything else at boot moving at once. Unlike the address injector it needs nobody at the machine: the host stays on the tailnet for the whole window, so a failed test is recoverable from anywhere with `docker compose up -d`. It refuses to run unless the platform is currently whole and, most importantly, unless `nexus-reconcile.log` shows the reconciler ran on *this* boot — the presence of a plist is not evidence that launchd loaded it, and rebooting with the stack down and nothing scheduled to raise it is the one way this injection becomes an outage instead of a test. What it reproduces is the state, not the cause: why Docker Desktop restored nothing that once is still unproven.

**It was run on 2026-07-26 at 21:51 and the second path walked, 51 seconds into the boot.** The stack was stopped at 21:50:38, the machine rebooted, and the reconciler started 7 seconds into the boot, had the address at 21:51:45, found all nine services missing at 21:52:01, and reported `stack up: all expected services running` followed by `all published bindings intact` at 21:52:14. Docker Desktop restored *none* of the nine, which is the first observation of the `unless` in `restart: unless-stopped` surviving a reboot on this machine rather than merely being promised by the compose file. The last line was `intact` and not `OK: all bindings restored`, as predicted before the run: the reconciler waits for the address first, so by the time `up -d` ran the forwards were built correctly on the first attempt, and no `can't assign requested address` appears in the backend log for this boot. Two injectors, two paths, neither substitutable for the other — now evidenced rather than argued. What it does not establish is Docker's restore failing unaided, which remains the 19:10 boot alone.

**The cost of the repair at boot is roughly double the hand-tested cost, which is itself the finding.** The named-set precondition took 27 seconds against a stable 16 on four healthy boots, and the binding scan took 40 seconds — twelve seconds between each of the three detections — where on a healthy boot the same scan completes inside one second. `broken_services()` contains no sleep, so that is entirely `docker inspect` latency while the machine is still busy. Of the 77 seconds from address to restored, more than half was spent looking rather than repairing.

**The 21:51 injection narrows what that cost is actually attributable to.** The same settle loop took 15 seconds there — its structural floor, four samples with three five-second sleeps, the fastest it can complete and still be the loop — and the binding scan did not appear at all. The difference is not boot versus hand test: it is whether there is a *running* stack to inspect. Against nine stopped containers the `docker compose ps` calls cost nothing measurable; against nine running ones on a busy boot they cost 11 seconds over the healthy baseline and the `docker inspect` sweep costs 40. Of the reconciler's 44 seconds at 21:51, 31 were waiting (15 address, 1 daemon, 15 settle) and 13 were `up -d` taking nine services from nothing to all-running, postgres health gate and `migrate` included. That 13 seconds is the figure no hand test had produced: the one hand run of this path took 16 seconds for a single already-imaged service, essentially all of it the settle loop.

**The cause recorded here until 2026-07-26 was wrong**, and it is worth keeping the correction rather than quietly replacing it. It named a logtail bootstrap-DNS retry loop. The third boot ran that loop in full — twelve DERP hosts, then a second round for `controlplane.tailscale.com` — and still passed with two seconds to spare; every attempt in it fails inside one second with `network is unreachable` rather than timing out, and all four boots in the log ran it. It was correlation, read as cause from two data points. The evidence and the correction are in [PROGRESS.md](../PROGRESS.md) 2026-07-26.

The ordering therefore cannot be relied on in either direction, and the reconciler below is the only thing that covers a lost race.

This paragraph previously said to rely on `restart: unless-stopped` to recover once the interface appears, and told the reader to confirm rather than assume. The confirmation disproved it. **A failed bind does not stop the container.** Docker Desktop logs one warning, does not retry, and the container starts normally; with nothing exited, the restart policy has no event to act on. The result is nine containers `Up`, the gateway reporting `healthy`, and four of six published ports simply absent — a state in which `docker compose ps` looks entirely correct.

The recovery is `launchd/reconcile-port-bindings.sh`, installed as a LaunchDaemon (runbook §7). It waits for the address to be on an interface, the daemon to answer, and the set of running services to stop changing; it then brings up whatever is not running (the second failure, below) and recreates only the containers whose requested `PortBindings` have an empty `NetworkSettings.Ports`.

**A second failure at boot needs the same daemon, and it is not a variant of the first.** On the 2026-07-26 19:10 boot — the macOS 26.5.2 update reboot, recorded in `InstallHistory.plist` at 19:09:47 — Docker Desktop restored *nothing*: all nine containers had stopped cleanly at the 19:04 shutdown, the engine was running again at 19:10:37, and no `exposer.Add` was ever logged — against a full nine on the 18:08 boot. Whether the update reboot is what made the difference is unproven and nothing here depends on it; the two boots that restored were plain reboots, which is one correlation. The containers, their configuration and their restart policy were all intact; they were simply never started. `restart: unless-stopped` is a promise the Docker daemon makes, kept on the two boots before that one and broken on this one, and **nothing else on this host ever ran `docker compose up`** — the reconciler's own repair path fires only for containers that are already running with a dropped forward. There was no second line of defence, and the platform stayed down until a person looked.

**The reconciler reported success while standing in it.** Its third precondition waited for the container count to stop changing but required the count to exceed zero before it would settle, so an empty platform spun to the ten-minute deadline, and the binding sweep then found nothing wrong because a sweep over running containers finds nothing wrong when there are none: `all published bindings intact; nothing to do`, exit 0. That is the third instance of this document's recurring defect — a check whose timing or scope lets it produce only one answer — and it was in the code written to fix the second one.

**So the precondition now waits for a named set, not a count.** A count cannot distinguish "not restored yet" from "not coming back"; a list of expected services can, because a service that is absent is still in the list. Whatever is missing is brought up with `docker compose up -d`, the result is read back rather than assumed, and a platform that is still incomplete exits non-zero even when every binding that does exist is correct. The list is named in both this script and `check-platform-health.sh`, for the same reason each of them needs it. Keeping the two in step by hand did not work: `parser` and `qdrant` were absent from the health sweep's copy from the day each service was added until 2026-08-04 — six days for `parser` (added 07-29), five for `qdrant` (07-30) — so either could have stopped without it noticing. This paragraph said "four months" until 2026-08-18, which is longer than the repository has existed (first commit 2026-07-24); a figure nobody could have measured, in the sentence about a list nobody was checking, is the enumeration error this document keeps recording arriving twice over. The reconciler's copy was missing the same two, and that is the worse half: its list drives both the settle precondition and the `docker compose up -d` repair, so on a boot where Docker restored nothing — the 19:10 path this section is about — `parser` and `qdrant` would have been left down while it logged `all expected services running` and exited 0. The component whose job is the repair was blind to two of the services it was repairing. Since 2026-08-04 both scripts derive the list from `docker compose config --services` minus `migrate`, each keeping a literal only as the fallback for when that derivation fails, and the reconciler logs which list it ended up with.

**The read-back gets its own 120 seconds rather than what is left of the run's.** The deadline is absolute and one of the two ways into the repair branch is the settle loop timing out — the 19:10 boot's exact path — which leaves nothing. With nothing left, the first sample, taken in the gap between `up -d` returning and Compose reporting the container as running, prints `FATAL: still not running` about a stack that is starting. Reproduced with one injected lagging sample: without the fix, the FATAL is logged in the same second as `Container ... Started`; with it, one retry and `stack up: all expected services running`. A repair whose failure report is a race is not one anyone can act on.

**It must recreate, not restart.** The forward is established when a container is *created*: `docker compose up -d` is a no-op against a container already running with a matching config, and `docker compose restart` reuses the container and leaves the backend's forwarding table untouched. Both were tried on the target host and neither restored a single binding; only `--force-recreate` did.

**That applies to the running container with a dead forward, and not to the stopped one**, which is why the script uses each in its own branch. A stopped service is started by a plain `up -d` and its forward is established at that moment: `grafana` stopped by hand and brought back this way had `127.0.0.1:3002` requested-equals-actual immediately afterwards, with `/login` returning 200. The distinction matters because using `--force-recreate` for both would rebuild containers a start would have fixed, and using `up -d` for both would silently do nothing in the case the script was originally written for.

**Checking for this state.** `docker compose ps` cannot see it. Compare requested against actual — an empty list on the actual side is the signature, while `null` means the service never published anything:

```bash
for c in $(docker compose ps -q); do
  printf '%-38s %s\n' "$(docker inspect $c --format '{{.Name}}')" \
    "$(docker inspect $c --format '{{json .NetworkSettings.Ports}}')"
done
```

**And something has to run that check when nobody is looking.** The reconciler covers the boot; a reconcile that fails, or a daemon that never runs, leaves precisely the state above with nothing to announce it — the original fault was found only because a person read four logs by hand. `launchd/check-platform-health.sh` (runbook §7) runs every five minutes and mails on a change of state: the expected service list, requested-versus-actual bindings, the six entrances over their published ports, and Ollama answering on loopback but not on the tailnet address. Three properties are deliberate. It compares services against a fixed expected list rather than enumerating what is running, because a container that is entirely gone would otherwise not appear in the enumeration and the sweep would report success. It asks that question as `docker compose ps --services --status running`, because plain `ps` excludes only *stopped* containers and would count a paused or restarting one as running — Docker Desktop's Resource Saver pauses containers, and `postgres`, `redis` and `prometheus` have no entrance probe, so this check is the whole of their coverage. And it sends a heartbeat daily even when nothing is wrong: a monitor on the host it watches can report "up but not serving" and can never report "powered off", so the only way silence becomes evidence is for something to be expected to break it.

**Its own liveness is the state file's mtime, and that had a hole exactly where it was read.** The log is events-only, so "did this ever run" is answered by `/opt/homebrew/var/nexus-health.state`, which every run rewrites — and the runbook's acceptance criterion is that the mtime is under five minutes old. With the plist at `RunAtLoad=false` and a 300-second interval, no run happened in the first five minutes of a boot, so the freshest mtime available in that window predated the boot: three to eight minutes old depending only on where the reboot fell in the previous interval, against a five-minute criterion. The 20:24 and 20:29 reboots were 4m37s apart and no run happened across either of them; the 20:26 check passed with thirteen seconds to spare, by luck. `RunAtLoad` is now true and the boot-time run is suppressed by the boot grace, which rewrites the state file verbatim and exits — it claims nothing, because nothing was checked, and updates the one thing it is entitled to claim.

**The boot grace it relies on to do that had never fired.** It parsed `sysctl -n kern.boottime`, whose output is `{ sec = 1785068938, usec = 428375 } ...`, with `s/.*sec = \([0-9]*\).*/\1/`; the leading `.*` is greedy and matched through to `usec`, so the boot time was the microseconds field, uptime was the Unix epoch, and the comparison could only ever answer "not in grace". That is the fourth instance of this document's recurring defect, and this time it was in the check whose only job was to have two answers — it also put a nine-digit `uptime` line in every alert mail sent before the fix. The pattern is now anchored at the start of the line, and the grace is 240 seconds rather than 300 so that it sits clearly below the interval instead of on the boundary, where whether the first scheduled run of a boot evaluates or is skipped came down to how long launchd took to load the job.

**The 21:02 boot confirmed the whole arrangement, and the confirmation did not come from the state file.** That file's mtime cannot distinguish the two designs: `StartInterval` counts from load either way, so the first scheduled write lands at load+300 whether `RunAtLoad` fired or not, and it overwrites the boot-time write five minutes later. The unified log separates them — four spawn/exit pairs, at 21:02:43.356→.473, 21:07:43.678→44.286, 21:12:44.309→.838 and 21:17:44.858→45.386. The first ran at an uptime of seven seconds and finished in **117 milliseconds**; the three full-path runs cluster at 528–608ms, because that path makes six curl probes, a `docker info`, a `docker compose ps` and ten `docker inspect` calls. Nothing but the grace path exits 0 in a tenth of a second while writing no log line, and none of the four sent mail. `launchctl print`'s `runs` counter is the wrong instrument here: it carries no timestamp, so `runs = 3` cannot be told apart from `RunAtLoad` plus two intervals without separately recovering when it was read.

**And the boundary the 240 was chosen to avoid turned out to be seven seconds away.** The first scheduled run of that boot fired at an uptime of 307 seconds. Had the grace stayed at 300 it would have evaluated by a seven-second margin; eight seconds more launchd latency and the same healthy boot would have skipped it and pushed the first real check to ten minutes. The coin flip described above was not hypothetical, and 240 turns that seven-second margin into sixty-seven.

**The grace also did its actual job for the first time on that boot.** From 21:02:56 to 21:05:31 the platform was genuinely broken — three bindings dropped, three tailnet entrances down — and no mail went out, because every moment of it fell inside the window the reconciler owns. Before 20:45 the grace could not fire at all, and after the fix there had been no failing boot to exercise it. Had the repair not worked, the 21:07:43 run would have caught it and mailed, which puts the worst-case detection delay at ten minutes.

## 10. Configuration and Secrets

Non-secret values are environment variables; secrets are mounted files read through `secrets_dir` ([backend.md](./backend.md) §8).

**Environment**

| Variable | Example | Notes |
|---|---|---|
| `ENV` | `production` | `development` locally |
| `AUTH_MODE` | `tailnet` / `local` / `dev` | `dev` refuses to start when `ENV=production`. Read in six places, not one; see [backend.md](./backend.md) §10 |
| `LOG_LEVEL` | `INFO` | This application's own `app.*` loggers, deliberately not the root, so raising it does not add a line per httpx call to the runtime. The lines below WARNING are the ones that say *why* a request was refused — `perimeter_rejected` is the only place the three causes of a 400 `untrusted_proxy` are distinguished, and the response distinguishes none of them |
| `DEV_TAILNET_LOGIN` | `dev@localhost` | Substituted for the absent `Tailscale-User-Login` header under `AUTH_MODE=dev`; set it to `BOOTSTRAP_ADMIN_LOGIN` to bootstrap locally |
| `TAILNET_IP` | `100.x.y.z` | Used for host-side port binding |
| `PROXY_HOSTNAME` | `llmapi.rcsl.online` | |
| `GATEWAY_BASE_URL` | empty | Where callers reach the inference API, shown in the management UI beside a newly issued key. Empty derives `https://` plus `PROXY_HOSTNAME`; set it only when the public origin differs. It cannot be read off the request, because the entrance answering is the admin one, not the one being described |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Not an environment variable: mounted as the `database_url` secret, a different least-privilege account per service ([security.md](./security.md) §6) |
| `REDIS_URL` | `redis://redis:6379/0` | The password is a separate `redis_password` secret |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Runtime on the host |
| `MLX_BASE_URL` | `http://host.docker.internal:8080` | The second host-native runtime, same reason (§1) |
| `MLX_TOOL_CALLING_VERIFIED` | `false` | Whether a real tool call has been seen against *this* `mlx_lm.server` build. It cannot be probed: a model that declines to call a tool is indistinguishable from a server that discarded the field, so only a person who has read a call off the wire may set it. While false the adapter refuses such a request rather than serving prose to an agent that will wait forever |
| `HF_CACHE_HOST_PATH` | `./data/hf-cache` | Host directory behind `HF_HOME`. On the Mac Studio it points at the runtime account's `~/.cache/huggingface`, so a model downloaded through the admin UI is the one the host-native server then serves. The one place a container writes onto a host path, and it holds model files only |
| `ADMIN_API_URL` | `http://admin-tailnet:8001` | Set per frontend service in Compose, not from `.env` |
| `ADMIN_BASE_URL` | `http://localhost:3000` | Origin used to build invitation and reset links. Configured rather than taken from the request: the link is issued on whichever entrance the administrator happens to be using and must always point at the public one, since a tailnet URL handed to somebody without Tailscale is a link they cannot open |
| `EXPOSE_OPENAPI` | `false` | Opt-in; ignored under `ENV=production` |
| `CACHE_BACKEND` | `redis` | `memory` is per-process and refused in production |
| `SESSION_ABSOLUTE_TTL_SECONDS` | `43200` | Names and units match the Settings fields |
| `SESSION_IDLE_TTL_SECONDS` | `3600` | |
| `INVITATION_TTL_SECONDS` | `259200` | Invitation and reset link lifetime |
| `TOTP_ENROLMENT_TTL_SECONDS` | `600` | How long a generated-but-unproved TOTP secret is held. Short on purpose: an abandoned enrolment must not leave a usable second factor waiting, and expiry costs the user only a re-scan |
| `TOTP_ISSUER` | `RCSL AI Nexus` | Shown by the authenticator app beside the account |
| `COOKIE_SECURE` | `true` | **Refused when `ENV=production` is set with `false`**, and it is not merely a flag: the `__Host-` prefix below requires `Secure`, so turning this off for local development drops the prefix as well and the frontend must be told the new cookie name (`NEXT_PUBLIC_CSRF_COOKIE=nexus_csrf`). The prefix is what binds the session cookie to this exact origin, which is the browser-side half of §4's argument for two hostnames and two entrances |
| `SESSION_COOKIE_NAME` | `__Host-nexus_session` | |
| `CSRF_COOKIE_NAME` | `__Host-nexus_csrf` | |
| `CSRF_HEADER_NAME` | `X-CSRF-Token` | Double-submit token, public entrance only |
| `ALLOWED_COUNTRIES` | `TW,AU` | Empty disables the filter |
| `MAX_CONTEXT_LENGTH` | `122880` | Bounds prompt size before generation starts, tool definitions and replayed tool calls included. Raised from `32768` on 2026-08-05, from `65536` on 2026-08-14 and from `98304` on 2026-08-17, each time for agent clients. **Sized together with `REQUEST_TIMEOUT_SECONDS` and the model's registered `context_length`**: prompt evaluation sends no bytes, so the read timeout is what bounds it. The 105.5 tok/s once quoted here was the dense model's and made that coupling look tight at 932s against the 1200s below; `qwen36-35b-a3b-q8` measured 711-730 tok/s across three cold session starts on 2026-08-17, so a full context is 173s and the read timeout is no longer the binding constraint; separately, Ollama evaluates at most `num_ctx / 2` prompt tokens and silently drops the rest, so this must stay under half of every serving model's registered context. **That invariant is no longer maintained here by hand, because it was not being maintained**: on 2026-08-17 this value was exactly half of `qwen36-35b-a3b-q8`'s `196608` rather than below it, and `assist` — which routes to `qwen7b` alone — was being served truncated at `8192 / 2` whenever a conversation reached a second turn. `RouteChatRequest._refuse_what_this_target_would_truncate` now applies the rule against whichever model routing picked, so this value bounds hardware cost and that one bounds correctness; `qwen7b` was raised to its native `32768` the same evening. Keep them consistent anyway — a global ceiling above a target's half turns a start-of-task refusal into a mid-task one |
| `OLLAMA_MODELS_PATH` | `/ollama-models` | Where the host's Ollama model store is mounted, read-only. The platform reads the vocabulary and the chat template out of the GGUF a model `ref` resolves to and counts prompts with them instead of estimating from character widths; only the metadata header is ever read (11.9 MiB in front of 38.7 GB of tensors). `OLLAMA_MODELS_HOST_PATH` is the host directory behind it. Empty turns exact counting off and falls back to the estimate — the right setting for a host that serves MLX and holds no GGUF — with a log line per model saying so |
| `TOKEN_COUNTER_CACHE_SIZE` | `2` | How many vocabularies one process keeps built. Measured: 132 MB resident for a 248,320-entry vocabulary and about 25 MB for a second. Two is what this deployment needs; eviction is least-recently-used and costs a rebuild of about a quarter of a second |
| `GEOIP_DB_PATH` | `/data/GeoLite2-Country.mmdb` | Refreshed weekly by `launchd/refresh-geolite2.sh` (runbook §5.1), which restarts the two enforcing services only when the file actually changed — geoip2 opens the database once at startup, so a swap alone changes nothing. Said "monthly" until 2026-08-03 and described no mechanism that existed |
| `BOOTSTRAP_ADMIN_LOGIN` | `you@example.com` | Creates the first admin on first login through the **tailnet** entrance only, and only while `users` is empty. Inert thereafter |
| `NODE_ID`, `NODE_NAME` | `local` | The single compute node `provision` writes on every start. There is no node-registration endpoint until the SSRF guard ships ([security.md](./security.md) §7.2) |
| `NODE_TOTAL_MEMORY_GB` | `64` | Must match the real machine, and is the figure `MemoryBudgetService` refuses loads against. Too high lets the guardrail walk the host into swap; too low refuses models that would fit ([../ARCHITECTURE.md](../ARCHITECTURE.md) §0.2) |
| `NODE_HEARTBEAT_INTERVAL_SECONDS` | `30` | How often the admin entrances probe each node and write the observed status, so a routing requirement of `node_status: online` reflects reality rather than what provisioning wrote once. Admin entrances only — the gateway may not write `nodes` (§6 of [security.md](./security.md)). Zero or negative disables it |
| `MAX_CONCURRENT_INFERENCE` | `4` | Queueing depth, not throughput: the GPU serves one generation at a time |
| `QUEUE_WAIT_SECONDS` | `120` | How long a request may wait for a slot before `503 overloaded` with `Retry-After`. It exists because of the number two rows down: a slot can legitimately be held for 35 minutes, and before 2026-08-05 a caller arriving with every slot taken waited that long producing zero bytes and no code, which is indistinguishable from a hung deployment. §6 makes this class of setting the only line of defence, and a guardrail that refuses silently is half a guardrail. Zero or negative restores the unbounded queue |
| `MAX_TOKENS_CEILING` | `16384` | Counts a thinking model's reasoning as well as its answer |
| `GATEWAY_MAX_BODY_BYTES` | `4194304` | Request body ceiling, refused on `Content-Length` before a byte is read. **The one guardrail here that applies to callers who have not authenticated**: the key check is a FastAPI dependency and FastAPI parses the body before it resolves dependencies, so without this an anonymous caller reached an unbounded allocation — found 2026-08-07 by sending 200 MiB with no credential and being answered. Derived from `MAX_CONTEXT_LENGTH` rather than chosen, so raise it with that or not at all |
| `ADMIN_MAX_BODY_BYTES` | `41943040` | The admin entrances take uploads, so theirs is larger. It sits inside two orderings this document already argues: **above** the 32 MiB in `upload_policy.py`, so a file between the two is refused by the check that names the reason, and **below** the management host's nginx `client_max_body_size` (64m in §5) so ours is the limit that fires. The frontend's `middlewareClientMaxBodySize` must equal or exceed it — the hang described in [frontend.md](./frontend.md) §1 lived in exactly that gap |
| `OLLAMA_KEEP_ALIVE` | `-1` | Residency after a request. `-1` keeps the model loaded, making the registry's `loaded` state true; sent on every generation, since Ollama's own five-minute default applies to any request that omits it |
| `OLLAMA_THINKING` | `true` | Default only; a request's `think` field overrides it. `false` suppresses thinking. Never sends `think: true`: Ollama refuses it for models that do not support thinking |
| `REQUEST_TIMEOUT_SECONDS` | `1200` | Per-read HTTP timeout to the runtime: bounds a *stalled* stream, and therefore **prompt evaluation**, which sends no bytes. Raised from `300` on 2026-08-05 and from `600` on 2026-08-14, each time with the context ceiling above. The cost falls on a *hung* runtime rather than a busy one — a producing stream resets it on every chunk — so what it buys is that a cold full-context prefill is reachable at all |
| `GENERATION_DEADLINE_SECONDS` | `900` | Wall-clock bound on one generation, counted from the **first chunk** rather than the request, so reading a long prompt does not spend the budget for writing the answer. It therefore composes with the row above: one request's worst case is their sum, 2100 seconds — 35 minutes holding a concurrency slot, and the figure `QUEUE_WAIT_SECONDS` is argued against. The frontend's `experimental.proxyTimeout` must stay above the sum, or a cut arrives with no reason attached; it is 2,160,000 ms, which clears 2100 s by a minute |
| `METRICS_ENABLED` | `true` | Exposes `/metrics`; off lifts the production requirement for a real `metrics_scrape_token` |
| `PARSER_BASE_URL` | `http://parser:8000` | The isolated document parser. A sibling container on an internal network, deliberately *not* on `host.docker.internal` like the runtimes: this one must be able to reach nothing at all ([security.md](./security.md) §7.3) |
| `PARSER_TIMEOUT_SECONDS` | `120` | |
| `DOCUMENT_STORAGE_PATH` | `/var/lib/nexus/documents` | Inside the container, backed by the `documents` volume. A mounted volume rather than MinIO; see [../ARCHITECTURE.md](../ARCHITECTURE.md) §4 for that decision and the condition that would reverse it |
| `QDRANT_BASE_URL` | `http://qdrant:6333` | The passage index. Its API key is a file secret, because Qdrant ships with no authentication at all |
| `QDRANT_TIMEOUT_SECONDS` | `30` | |
| `POSTGRES_USER`, `POSTGRES_DB` | `nexus` | Role and database names are not secrets; the superuser password is. Read by the `postgres` container |
| `API_KEY_MAX_LIFETIME_DAYS` | `365` | Ceiling on how far ahead a key may be set to expire. Expiry exists to force rotation, and a mandatory field with no upper bound does not: an `expires_at` in the year 9999 satisfies "must be in the future" and rotates nothing. Also the figure the management assistant quotes |
| `ASSISTANT_MAX_TOKENS` | `1536` | Token ceiling for one advisory reply. Small on purpose: it answers in two or three sentences, and a reply that runs past the ceiling loses its proposal card rather than arriving malformed. The `assist` capability needs a routing policy of its own or the drawer reports it has no model to run on |

`API_KEY_PEPPER_PREVIOUS` was listed here until 2026-08-18 and is not an
environment variable: it is a file secret, empty except during a pepper
rotation, and it appears in the secrets table below. A secret named in both
tables is the one shape this section most needs to avoid, since an environment
variable outranks a file secret in pydantic-settings.

**Secrets** (`/run/secrets`, never environment variables)

Wired. `docker-compose.yml` declares a `secrets:` block backed by files under
`./secrets`, and each service mounts only what its role needs. `Settings` reads
them through `secrets_dir`. An environment variable outranks a file secret in
pydantic-settings, so a secret left in `.env` would silently override the mount;
`.env` therefore carries only non-secret configuration, and `secrets/README.md`
holds the setup. One file per credential, raw value, no trailing newline.

| Secret | Purpose | Mounted into |
|---|---|---|
| `owner_database_url` | Schema owner (DDL); URL | `migrate` only |
| `gateway_database_url` | Gateway account; URL. Writes `usage_records`, `prompt_logs` and `refusals` — this row said `usage_records` alone until 2026-08-18 — and reads every table **except** `prompt_logs` and `refusals`, which are subtracted from the blanket `SELECT` after it. The asymmetry is deliberate and is the whole of the argument: the one process exposed to the internet appends its own transcripts and refusals and can read none of them, which is the same split Qdrant's read-only key makes in the other direction. The names are in `db_roles.py`, in code, because they are a security decision that belongs under review rather than in a deployment file | `gateway`; and `migrate`, to provision the role |
| `admin_database_url` | Admin account (full DML, no DDL); URL | both admin entrances; and `migrate` |
| `postgres_password` | Superuser password; must equal the password in `owner_database_url` | `postgres` |
| `redis_password` | Read from the file in redis's command; no `_FILE` convention | `redis`, and the services that use redis |
| `api_key_pepper` | HMAC pepper | every backend service and `migrate` |
| `api_key_pepper_previous` | Accepted during a rotation, so keys signed with the old pepper keep verifying until they are reissued. Not shipped as a file, because it is empty except during one | none by default; add the secret and mount it into the backend services for the duration of a rotation |
| `totp_encryption_key` | Encrypts TOTP secrets at rest | backend services, `migrate` |
| `session_signing_key` | Present for completeness; sessions are opaque Redis ids | backend services, `migrate` |
| `proxy_shared_secret` | Matches `X-Nexus-Proxy` in nginx | backend services, `migrate` |
| `metrics_scrape_token` | Bearer token for `/metrics`; the same file is mounted into Prometheus | backend services, `migrate`, `prometheus` |
| `grafana_admin_password` | Grafana's initial admin password | `grafana` |
| `qdrant_api_key` | Qdrant's API key. It ships with **no authentication at all**, so this is not hardening but the only control between anything on the admin network and a full read of the knowledge base. Required to be a real value in production unconditionally, unlike `metrics_scrape_token` | `qdrant`, the two admin entrances, `migrate` |
| `qdrant_read_only_api_key` | A **different** value, and the vector store's half of the [security.md](./security.md) §6 least-privilege split. Mounted into `gateway` at the target name `qdrant_api_key`, so retrieving a passage to answer a request cannot become writing one. Verified against a live Qdrant: this key gets 200 on a search and 403 on a collection write | `qdrant`, `gateway` (as `qdrant_api_key`) |
| `alert_smtp_account` | The Gmail address `launchd/check-platform-health.sh` sends alerts *from*. Not itself a secret, but kept beside the password because Gmail requires the envelope sender to be the account that authenticates | no container; read from `./secrets` by the health daemon on the host |
| `alert_smtp_password` | A Google app password for that account, not the account password. Needs 2-Step Verification enabled on the account first | no container; the health daemon |
| `maxmind_license_key` | The MaxMind account's permanent licence key, read by `launchd/refresh-geolite2.sh`. The long-lived credential, unlike the throwaway token the first download used; without it `GEOIP_DB_PATH` rots in place, which is a country filter that quietly stops being current rather than one that fails | no container; the weekly refresh job |

**The last three are read by launchd jobs on the host, not mounted into any
container, and that is why this table did not list them until 2026-08-18.** The
table was assembled from `docker-compose.yml`'s `secrets:` block, which cannot
see them. Neither is needed if the corresponding daemon is not installed, and
`secrets/README.md` says so per file — but a deployment that copies only what is
listed here installs the health daemon and gets no mail, or installs the refresh
job and gets a fatal on its first run.

MinIO is absent and will stay absent: document storage is a mounted volume, not
object storage. See [ARCHITECTURE.md](../ARCHITECTURE.md) §4 for that decision
and the condition that would reverse it.

The four crypto secrets, and `metrics_scrape_token` when metrics are enabled, are
mounted into `migrate` as well, because it calls `get_settings()`, which refuses
the shipped placeholders under `ENV=production`. `POSTGRES_USER` and `POSTGRES_DB`
stay non-secret environment values, read by the Postgres container.

`.env.example` lists every non-secret field with a development default, and
documents the secrets as file mounts rather than listing them, since a value
there would override the mount.

## 11. Local Development

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

`AUTH_MODE=dev` disables the country filter and the trusted-proxy check, and substitutes `DEV_TAILNET_LOGIN` for the Tailscale identity header the tailnet entrance would otherwise read. It does **not** inject a fixed admin `Actor` — see [backend.md](./backend.md) §10 — and the gateway still requires a real API key. Ollama can run natively on Windows with `OLLAMA_BASE_URL=http://host.docker.internal:11434`, exactly as in production.

**`AUTH_MODE=dev` combined with `ENV=production` is a startup failure**, not a warning. A misconfigured deployment refuses to boot rather than quietly serving an unauthenticated admin API. [security.md](./security.md) §14 carries a matching pre-launch check, and it is worth testing rather than assuming.

The local credential flow (invitation, password, TOTP) **is** reproducible locally, since it depends on nothing external. Run with `AUTH_MODE=local` to exercise it.

Not reproducible locally, and therefore only verifiable on the Mac Studio: GPU-backed inference, the tailnet entrance, and nginx behaviour.
