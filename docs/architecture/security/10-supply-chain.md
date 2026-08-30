# 10. Supply Chain

[← Security Architecture and Threat Model](../security.md)

| Layer | Control |
|---|---|
| Python | `uv` or Poetry with hashes pinned; `pip-audit` in CI |
| Node | `pnpm` lockfile; `pnpm audit` in CI |
| Docker images | **Pin digests, not `:latest`** — *stated here since the first draft and not what `docker-compose.yml` does.* Every image carries a version tag (`postgres:17-alpine`, `qdrant/qdrant:v1.13.0`, `redis:7-alpine`, `prom/prometheus:v3.1.0`, `grafana/grafana:11.5.1`) and not one carries a `@sha256:` digest. A tag is mutable, so this is "the version we chose" rather than "the bytes we reviewed": it closes `:latest`, which is the larger half, and leaves a tag repush able to change what a redeploy runs. Open, 2026-08-18. Trivy **is** in CI |
| Third-party services | Grafana, Qdrant and the base images all have CVE histories worth watching; subscribe to advisories and schedule updates. Open WebUI and MinIO were named here from the first draft and neither is deployed — Open WebUI is a possible *client* of the gateway rather than a service this platform runs, and document storage was built on a mounted volume instead of MinIO (§6) |

**shadcn/ui deserves specific mention.** It copies component source into the repository rather than being an npm dependency. That makes it fully controllable, at the cost of **not receiving upstream fixes automatically**. The underlying Base UI package remains an npm dependency and is covered by audit tooling, but the shadcn layer itself requires deliberate tracking of upstream changes. The same caveat applies to any chart library adopted on the same distribution model ([frontend.md](../frontend.md) §7).
