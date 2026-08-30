# 1. Core Principle: Separate the Control Plane From the Data Plane

[← Security Architecture and Threat Model](../security.md)

Everything else builds on this.

| | Data plane | Control plane |
|---|---|---|
| Contents | `/v1/chat/completions`, `/v1/embeddings` | `/admin/*` and the management UI |
| Exposure | Public | **Tailnet and public (two entrances)** |
| Authentication | API key | Tailscale identity / password with TOTP |
| Worst-case damage | Consume compute, read authorized knowledge | Full platform control, data theft, code execution on the host |
| Deployment | `gateway` container | `admin-tailnet` and `admin-public` containers |

**These must be separate container processes, not route groups inside one application.**

With a single service plus a reverse proxy rule blocking `/admin/*`, security rests entirely on one path-matching rule. One typo in the proxy config, one new route added without updating it, or one path-normalisation bypass (`/admin/..%2f`, mixed case, URL encoding) exposes the control plane. With separate containers, the isolation is guaranteed by **socket binding** rather than by string comparison.

**What this does and does not buy.** Splitting the containers blocks one specific attack: reaching `/admin/*` through the public data-plane path. It does **not** mean a compromised gateway is harmless. The gateway holds a database connection, the API key pepper, and every in-flight prompt in plaintext, and it can reach the runtimes. Mitigations for that separate problem are in §6 and §3.2, not here. An earlier draft claimed an attacker "would still need to move laterally"; that overstated the benefit and is corrected here.

This split costs no duplicated code: all backend containers run the same image and share the whole `domain/` and `application/` layers. Only the mounted routers differ.
