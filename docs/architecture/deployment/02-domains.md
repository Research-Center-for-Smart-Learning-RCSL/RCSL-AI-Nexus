# 2. Domains

[← Deployment Topology](../deployment.md)

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

**Both names are single-label, and that is the reason for them.** These replaced `ai.nexus.rcsl.online` and `api.nexus.rcsl.online` on 2026-08-04. A DNS wildcard matches any depth but a **TLS** wildcard matches exactly one label, so the two-label names resolved long before `*.rcsl.online` could serve them and needed certificates of their own ([ROADMAP.md](../../ROADMAP.md)). `llm` and `llmapi` are covered by the existing wildcard on both sides, and they no longer depend on nobody ever creating a `nexus.rcsl.online` node in the zone — which was the fragility recorded in [security.md](../security.md) §15.4. `llmapi` is one word rather than `api.llm.rcsl.online` for exactly this reason: a dot there would put the name back outside the wildcard certificate and reintroduce the dependency on the zone's shape.

What remains of §15.4 applies to any name here: the wildcard resolves *every* subdomain to the proxy host, so anyone able to obtain a vhost there can serve content under a plausible name. Explicit A records would close that; the wildcard predates this project and the domain is maintained by someone else.
