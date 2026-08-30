# 3. Network Architecture

[← Security Architecture and Threat Model](../security.md)

### 3.1 Public Entrance: External openresty Reverse Proxy

**Decided.** Public traffic arrives at `140.122.250.55` (NTNU, maintained by another administrator) and is forwarded over the tailnet to the Mac Studio. Full topology and nginx configuration in [deployment.md](../deployment.md).

The Mac Studio itself still has **no public IP and needs no inbound port opened on its network**. Only the reverse proxy is exposed.

| Approach | Inbound port needed | Edge protection | Third party sees plaintext | Response time cap | Outcome |
|---|---|---|---|---|---|
| **openresty proxy (adopted)** | No | None | **Yes** | Configurable | Existing proxy and certificate workflow, no additional cost |
| Cloudflare Tunnel | No | WAF, rate limit, DDoS | No | **100 s** | Evaluated below, not adopted |
| Router port forwarding | Yes | None | No | Configurable | Not considered |
| Tailscale Funnel | No | None | No | Configurable | Cannot serve a custom domain certificate |

Two consequences must be faced:

1. **TLS terminates on a third-party machine.** Its administrator is technically able to read plaintext traffic, including prompt content. Known and accepted, see §15.1.
2. **No edge protection at all.** All traffic reaches the Mac Studio, so the resource guardrails in §4.3 are promoted from "recommended" to **the only line of defence**.

#### 3.1.1 Cloudflare Tunnel Evaluation (July 2026, not adopted)

Cost was not the obstacle: Tunnel is free with no usage limits, DNS hosting is free, Access is free for up to 50 users, and basic WAF and DDoS protection are included. Two non-monetary costs decided it:

1. **Migration risk.** `rcsl.online` is served by Gandi nameservers and **the domain is actively receiving mail through Gandi** (`MX: spool.mail.gandi.net`, `SPF: include:_mailcust.gandi.net`). Moving nameservers touches mail delivery on a shared domain maintained by someone else.
2. **100-second origin response cap.** Cloudflare Free, Pro, and Business fix the 524 timeout at 100 seconds; only Enterprise can raise it. Streaming requests are unaffected because the connection stays open once the first token is sent, but **non-streaming long completions would be truncated**. The openresty path has no such limit.

A third option, registering a separate cheap domain on Cloudflare (roughly USD 10 per year, avoiding the migration risk entirely and requiring no coordination), is retained for future consideration.

If this is revisited, the migration path is in [deployment.md](../deployment.md) §8, and the accepted risk in §15.1 is then resolved.

### 3.2 Network Segmentation

**The invariant: the gateway shares no network with either admin entrance.** The
tailnet entrance trusts `Tailscale-User-Login` outright, so any container that
can reach it by service name can forge an administrator. Socket binding isolates
the host-published port, not the Docker service name, so if the gateway and the
tailnet entrance shared a network a compromised gateway could `curl
http://admin-tailnet:8001` with a forged header and take the control plane. The
data plane and the control plane therefore have separate database segments.

```yaml
networks:
  gateway-egress:        # non-internal; the gateway's route to the host runtime
  gateway-data:
    internal: true       # gateway <-> postgres/redis/qdrant, no internet
  control-tailnet:       # non-internal; frontend-tailnet <-> admin-tailnet + host
  control-public:        # non-internal; frontend-public <-> admin-public + host
  admin-data:
    internal: true       # both admin entrances <-> postgres/redis/qdrant, no internet
  parser-net:
    internal: true       # both admin entrances <-> parser, and nothing else (§7.3)
  metrics-gateway:
    internal: true       # prometheus -> gateway:/metrics
  metrics-admin:
    internal: true       # prometheus -> both admin entrances:/metrics
  metrics-viz:
    internal: true       # grafana -> prometheus, and no egress for either
  viz-ingress:           # non-internal; carries grafana's host port and nothing else
```

| Service | Networks | Host publish |
|---|---|---|
| gateway | gateway-egress, gateway-data, metrics-gateway | `100.x.x.x:8000` (tailnet only) |
| admin-tailnet | control-tailnet, admin-data, metrics-admin, parser-net | `127.0.0.1:8001` |
| admin-public | control-public, admin-data, metrics-admin, parser-net | `100.x.x.x:8002` (tailnet only) |
| frontend-tailnet | control-tailnet | `127.0.0.1:3000` |
| frontend-public | control-public | `100.x.x.x:3001` (tailnet only) |
| parser | parser-net | none |
| postgres, redis, qdrant | gateway-data, admin-data | none |
| prometheus | metrics-gateway, metrics-admin, metrics-viz | none |
| grafana | metrics-viz, viz-ingress | `127.0.0.1:3002` |
| migrate (one-shot) | admin-data | none |

**This table listed five networks and eight services until 2026-08-18**, having
been written when that was the whole of `docker-compose.yml` and never revisited
as the parser (§7.3) and the observability stack (§6) landed. Ten networks and
twelve services is what the file declares today. The invariant the section is
about survived the growth — the intersection of the gateway's networks with
either admin entrance's is still empty — but a segmentation model that omits
half the segments cannot be used to check that, which is the only thing it is for.

What this buys, service by service: the **gateway** touches only the database
and the host runtime, and has no path to any admin entrance. **frontend-public**,
which faces the internet through openresty, is on `control-public` only and so
cannot reach `admin-tailnet` either. The two admin entrances share `admin-data`
because they are the same trust tier (§1); a compromise of one is already a
control-plane compromise, so reaching the other over that segment is not an
escalation across the boundary that matters.

**postgres, redis and qdrant are the only members of both database segments, and that
is safe** because they accept connections and never open one. A shared datastore
is not a shared path: the gateway reaching postgres does not let it reach an
admin entrance through postgres. This paragraph named only the first two until
2026-08-18; qdrant has been dual-homed the same way since the knowledge base was
built, and the property it rests on is the same one — with the least-privilege
split of §6 on top of it, since the gateway holds Qdrant's read-only key and its
own database account rather than the admin ones.

**Model runtimes do not appear here.** Ollama and MLX run natively on the macOS
host bound to `127.0.0.1`; containers reach them through `host.docker.internal`,
which needs a non-internal network — `gateway-egress` for the gateway, the two
`control-*` networks for the admin entrances. The database segments stay
`internal: true`, so postgres and redis have no route off the machine.

An earlier draft defined a single `app` network shared by every application
container. That is what §15.5 recorded as a live exposure: the gateway and the
tailnet entrance sat on it together. The split above closes it. (An even earlier
draft had an `edge` network described as "the only segment that touches external
traffic"; that was always wrong, since Docker's published ports are unrelated to
Compose network membership, and it was removed.)

`internal: true` on the database segments is a genuine control but a narrow one.
It stops the database tier from reaching the internet; it does nothing about a
compromised gateway, which legitimately sits on `gateway-data` for its rate-limit
counters and usage records. §6 addresses that with per-service credentials and
least privilege.

### 3.3 Rule: No Port May Be Published on `0.0.0.0`

The most common and most damaging mistake in practice. **On Docker Desktop, `ports: - "5432:5432"` binds Postgres to every host interface**, so any device on the LAN (a guest phone, a compromised printer, another lab machine) can reach the database.

```yaml
# Wrong: exposed to the entire LAN
ports:
  - "5432:5432"

# Right: internal services publish nothing; containers reach each other by service name

# Right: reachable only from the proxy, over the tailnet
ports:
  - "${TAILNET_IP}:8000:8000"

# Right: browser-facing service on loopback, exposed through tailscale serve
ports:
  - "127.0.0.1:3000:3000"
```

**This rule concerns the host side of a port mapping, not the bind address inside the container.** Uvicorn must still listen on `0.0.0.0` inside its container, otherwise the published port forwards to nothing. The two are frequently confused and the distinction is what makes the rule workable.

```bash
tailscale serve --bg --https 443  http://127.0.0.1:3000   # management UI
tailscale serve --bg --https 8443 http://127.0.0.1:3002   # Grafana (Phase 2)
```

### 3.4 Tailscale ACL

Being on the tailnet must not imply reaching everything. Note in particular that without the rules below, **any tailnet member could connect directly to `100.x.x.x:8000` or `:8002` and bypass every control applied at the proxy**.

```json
{
  "groups": {
    "group:ai-admin": ["you@example.com"],
    "group:ai-user":  ["colleague-a@example.com"]
  },
  "tagOwners": {
    "tag:ai-server":  ["group:ai-admin"],
    "tag:ntnu-proxy": ["group:ai-admin"]
  },
  "acls": [
    { "action": "accept", "src": ["tag:ntnu-proxy"], "dst": ["tag:ai-server:8000,8002,3001"] },
    { "action": "accept", "src": ["group:ai-admin"], "dst": ["tag:ai-server:443,8443,22"] },
    { "action": "accept", "src": ["group:ai-user"],  "dst": ["tag:ai-server:443"] }
  ],
  "ssh": [
    {
      "action": "check",
      "src": ["group:ai-admin"],
      "dst": ["tag:ai-server"],
      "users": ["ops"],
      "checkPeriod": "12h"
    }
  ],
  "tests": [
    {
      "src": "you@example.com",
      "accept": ["tag:ai-server:443", "tag:ai-server:8443"],
      "deny": ["tag:ai-server:8000", "tag:ai-server:8002", "tag:ai-server:3001"]
    },
    {
      "src": "tag:ntnu-proxy",
      "accept": ["tag:ai-server:8000", "tag:ai-server:8002", "tag:ai-server:3001"],
      "deny": ["tag:ai-server:443", "tag:ai-server:8443"]
    }
  ]
}
```

The proxy machine carries `tag:ntnu-proxy` and can reach only the three ports it needs. Human members reach only the `tailscale serve` endpoints on 443 and 8443. `"action": "check"` forces SSH re-authentication even from an enrolled device, which supports the "SSH is repair mode" posture.

**The `tests` block is the part that keeps this true.** Tailscale runs it on every policy save and refuses a policy that fails one, so the `deny` lines are the no-bypass property asserted rather than described: a human member must not reach the data-plane ports, and the proxy must not reach the management endpoints. Without them the rules above are a claim that only holds until someone edits the file.

**A tagged device is required, not incidental.** Every rule here has `tag:ai-server` on the destination side, so a server that joined the tailnet without `--advertise-tags` matches none of them — and since the default policy for a new tailnet is `{"src": ["*"], "dst": ["*"], "ip": ["*"]}`, the failure mode is not "nothing works" but "everything is reachable". The tag also disables Tailscale's default 180-day key expiry, which on a 24/7 server would otherwise take the tailnet down half a year after deployment.

**Tailscale SSH needs both halves, and neither alone is enough.** Port 22 in the `acls` rule above carries the connection; the `ssh` block below authorises the session. With only the port, `tailscaled` answers and then refuses with `tailnet policy does not permit you to SSH to this node`; with only the `ssh` block, nothing reaches port 22 at all. The two failures look different and are equally easy to mistake for the SSH server being absent.

**A tagged node has no user identity, and that has a consequence beyond SSH.** `tailscale whois` for `tag:ai-server` lists tags and no user, so `tailscale serve` has no `Tailscale-User-Login` to inject for a connection originating from the server itself. The tailnet management entrance therefore cannot be exercised from the machine it runs on — testing it needs a second, user-owned device. This is a property of tagging, not a misconfiguration.
