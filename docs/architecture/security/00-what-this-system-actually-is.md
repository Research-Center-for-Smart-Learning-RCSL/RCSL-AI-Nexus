# 0. What This System Actually Is

[← Security Architecture and Threat Model](../security.md)

Before discussing controls, an honest description of the risk profile, because it differs from a typical side project:

1. A **24/7 physical machine** sitting in a research facility.
2. It **executes model files downloaded from the internet**. Some model formats are equivalent to arbitrary code execution on load.
3. It holds **the team's unpublished research data** (knowledge base documents, prompt content).
4. It exposes a **programmable API to the public internet**. Anyone holding a key can consume the hardware.
5. Its **management interface can load and unload models, change routing, and mint API keys**, which amounts to full control of the platform.

Confirmed premises:

| Item | Decision |
|---|---|
| Access boundary | Hybrid. The gateway API is public. The management UI has two entrances: tailnet and public |
| Role model | `admin` / `user` separation |
| Data sensitivity | Internal unpublished research. No personal data, but disclosure causes real harm |
| Management authentication | Tailscale identity on the tailnet; invitation-only local accounts with mandatory TOTP on the public entrance |
| Tenancy | **Single tenant through Phase 1.** See [../ARCHITECTURE.md](../../ARCHITECTURE.md) §2.8 |
| Runtime placement | **Native on the macOS host**, not in Docker. See [../ARCHITECTURE.md](../../ARCHITECTURE.md) §0.1 |
