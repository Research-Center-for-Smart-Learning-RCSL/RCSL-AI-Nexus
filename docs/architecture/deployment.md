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

**Observability runs as two containers.** Prometheus scrapes the three applications' `/metrics` and Grafana reads Prometheus. Prometheus is on internal-only networks and publishes no host port. Grafana binds `127.0.0.1:3002`, exposed to the tailnet through `tailscale serve --https 8443` for operators, and therefore cannot be internal-only: Docker will not publish a host port into an `internal` network, so Grafana carries a dedicated non-internal `viz-ingress` alongside its internal link to Prometheus (§6 of security.md explains the trade and why Prometheus is deliberately not given the same). Neither is reachable from the public entrance. See [security.md](./security.md) §6.

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
                                          password + TOTP session; strips every Tailscale-* header

Data plane
  external service --public--> openresty --tailnet--> TAILNET_IP:8000 --> gateway
        api.nexus.rcsl.online                                              API key auth
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

## 8.1 Source Availability Obligation

The project is licensed under AGPL-3.0, whose section 13 treats network
interaction as distribution. Both public hostnames in section 2 are exactly
the trigger: anyone reaching `ai.nexus.rcsl.online` or
`api.nexus.rcsl.online` is entitled to the source of the version being run,
including local modifications.

This is an operational obligation, not a one-time licensing formality, so it
belongs in the deployment runbook:

- Keep the deployed revision published, and link to it from the management UI
  footer rather than fielding requests individually.
- Tag or otherwise identify what is actually running, so the offered source
  corresponds to the deployed build rather than to whatever is on `main`.

## 9. Build, Deploy, and Upgrade

**Images are built on the Mac Studio.** The development machine is Windows on x86 and the target is arm64, so `docker compose build` runs on the target host. This avoids operating a registry and cross-platform builds for a single-node deployment. If a second node is added later, publishing arm64 images to GHCR becomes worthwhile.

**Migrations run as a one-shot service**, never from an application entrypoint, because three containers start from the same image and would otherwise race:

```yaml
migrate:
  image: rcsl-ai-nexus:latest
  command: ["sh", "-c", "alembic upgrade head && python -m app.infrastructure.provision"]
  networks: [admin-data]
  restart: "no"
```

Every application service declares `depends_on: { migrate: { condition: service_completed_successfully } }`. The `provision` step after the migration writes the single configured compute node (there is no node-registration endpoint until the SSRF guard ships; see [security.md](./security.md) §7.2) and reconciles any model left in a transient state by a crash.

**Routine upgrade**

```bash
git pull
docker compose build
docker compose up -d          # migrate runs first, then services restart
docker compose ps             # confirm migrate exited 0 and services are healthy
```

After any `up -d` that recreates containers, also confirm the published ports are actually bound — see the startup-ordering note below for why `docker compose ps` does not show this.

**Rollback.** Check out the previous tag and rebuild. Alembic downgrades are written only where a migration is genuinely reversible; otherwise recovery is a database restore, which is why §9.4 of [security.md](./security.md) insists restores are rehearsed.

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

**So the precondition now waits for a named set, not a count.** A count cannot distinguish "not restored yet" from "not coming back"; a list of expected services can, because a service that is absent is still in the list. Whatever is missing is brought up with `docker compose up -d`, the result is read back rather than assumed, and a platform that is still incomplete exits non-zero even when every binding that does exist is correct. The list is named in both this script and `check-platform-health.sh`, for the same reason each of them needs it, so a service added to Compose must be added to both.

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
| `AUTH_MODE` | `tailnet` / `local` / `dev` | `dev` refuses to start when `ENV=production` |
| `TAILNET_IP` | `100.x.y.z` | Used for host-side port binding |
| `PROXY_HOSTNAME` | `api.nexus.rcsl.online` | |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Not an environment variable: mounted as the `database_url` secret, a different least-privilege account per service (§6) |
| `REDIS_URL` | `redis://redis:6379/0` | The password is a separate `redis_password` secret |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Runtime on the host |
| `ADMIN_API_URL` | `http://admin-tailnet:8001` | Set per frontend service in Compose, not from `.env` |
| `EXPOSE_OPENAPI` | `false` | Opt-in; ignored under `ENV=production` |
| `CACHE_BACKEND` | `redis` | `memory` is per-process and refused in production |
| `SESSION_ABSOLUTE_TTL_SECONDS` | `43200` | Names and units match the Settings fields |
| `SESSION_IDLE_TTL_SECONDS` | `3600` | |
| `INVITATION_TTL_SECONDS` | `259200` | Invitation and reset link lifetime |
| `ALLOWED_COUNTRIES` | `TW,AU` | Empty disables the filter |
| `MAX_CONTEXT_LENGTH` | `32768` | Bounds prompt size before generation starts |
| `API_KEY_PEPPER_PREVIOUS` | empty | Set only during a rotation |
| `GEOIP_DB_PATH` | `/data/GeoLite2-Country.mmdb` | Refreshed monthly |
| `BOOTSTRAP_ADMIN_LOGIN` | `you@example.com` | Inert once any user exists |
| `MAX_CONCURRENT_INFERENCE` | `4` | Queueing depth, not throughput: the GPU serves one generation at a time |
| `MAX_TOKENS_CEILING` | `16384` | Counts a thinking model's reasoning as well as its answer |
| `OLLAMA_THINKING` | `true` | Default only; a request's `think` field overrides it. `false` suppresses thinking. Never sends `think: true`: Ollama refuses it for models that do not support thinking |
| `REQUEST_TIMEOUT_SECONDS` | `300` | Per-read HTTP timeout to the runtime: bounds a *stalled* stream |
| `GENERATION_DEADLINE_SECONDS` | `900` | Wall-clock bound on one generation. The frontend's `experimental.proxyTimeout` must stay above it, or a cut arrives with no reason attached |
| `METRICS_ENABLED` | `true` | Exposes `/metrics`; off lifts the production requirement for a real `metrics_scrape_token` |

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
| `gateway_database_url` | Gateway account (read all, write `usage_records`); URL | `gateway`; and `migrate`, to provision the role |
| `admin_database_url` | Admin account (full DML, no DDL); URL | both admin entrances; and `migrate` |
| `postgres_password` | Superuser password; must equal the password in `owner_database_url` | `postgres` |
| `redis_password` | Read from the file in redis's command; no `_FILE` convention | `redis`, and the services that use redis |
| `api_key_pepper` | HMAC pepper | every backend service and `migrate` |
| `api_key_pepper_previous` | Accepted during a rotation; add only for its duration | (as needed) |
| `totp_encryption_key` | Encrypts TOTP secrets at rest | backend services, `migrate` |
| `session_signing_key` | Present for completeness; sessions are opaque Redis ids | backend services, `migrate` |
| `proxy_shared_secret` | Matches `X-Nexus-Proxy` in nginx | backend services, `migrate` |
| `metrics_scrape_token` | Bearer token for `/metrics`; the same file is mounted into Prometheus | backend services, `migrate`, `prometheus` |
| `grafana_admin_password` | Grafana's initial admin password | `grafana` |
| `qdrant_api_key`, `minio_root_password` | Phase 2 | not yet |

The four crypto secrets, and `metrics_scrape_token` when metrics are enabled, are
mounted into `migrate` as well, because it calls `get_settings()`, which refuses
the shipped placeholders under `ENV=production`. `POSTGRES_USER` and `POSTGRES_DB`
stay non-secret environment values, read by the Postgres container.

`.env.example` lists every non-secret field with a development default, and
documents the secrets as file mounts rather than listing them, since a value
there would override the mount.

## 11. Local Development

The Windows development machine has no `tailscale serve`, no openresty, and no GeoLite2 database. Taken literally, the middleware described here rejects every request and nothing runs locally.

```bash
ENV=development
AUTH_MODE=dev
```

This injects a fixed admin `Actor`, and disables the country filter and the trusted-proxy check. Ollama can run natively on Windows with `OLLAMA_BASE_URL=http://host.docker.internal:11434`, exactly as in production.

**`AUTH_MODE=dev` combined with `ENV=production` is a startup failure**, not a warning. A misconfigured deployment refuses to boot rather than quietly serving an unauthenticated admin API. [security.md](./security.md) §14 carries a matching pre-launch check, and it is worth testing rather than assuming.

The local credential flow (invitation, password, TOTP) **is** reproducible locally, since it depends on nothing external. Run with `AUTH_MODE=local` to exercise it.

Not reproducible locally, and therefore only verifiable on the Mac Studio: GPU-backed inference, the tailnet entrance, and nginx behaviour.
