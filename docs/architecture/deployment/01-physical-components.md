# 1. Physical Components

[← Deployment Topology](../deployment.md)

| Role | Machine | Notes |
|---|---|---|
| Compute host | Mac Studio | Runs all containers, plus the model runtimes natively. **No public IP**, tailnet only |
| Public entrance | `140.122.250.55` (NTNU) | openresty reverse proxy only. **Runs none of this project's services and stores none of its data** |
| Client devices | Laptops, phones | With Tailscale, over the tailnet; without it, through the public entrance |

The proxy host is maintained by another administrator. This project asks only that it join the tailnet and forward two hostnames.

**Model runtimes are not containers.** Ollama and MLX run natively on macOS under launchd, bound to `127.0.0.1`, because Docker on macOS cannot reach the GPU. Containers connect through `host.docker.internal:11434`. Rationale in [ARCHITECTURE.md](../../ARCHITECTURE.md) §0.1; host-level hardening in [security.md](../security.md) §7.1(d).

**Ollama runs as its own account, and the model store had to move for it.** Since 2026-08-18 `launchd/online.rcsl.ollama.plist` names `UserName` `_rcslollama` — uid 470, no login shell, not in `admin` — adopted by `launchd/adopt-ollama-service-account.sh`. The weights live at `/Users/Shared/ollama/models` rather than under the operator's home, and that move is what unblocked five months of the change rather than being an incidental tidy-up: `/Users/<operator>` is mode 750, so no account outside `staff` can traverse into it and no service account could have read the store where it was. The directory is `_rcslollama:staff` at 750 — group `staff` rather than the service account's own group because Docker Desktop shares the path as the operator and three backend containers bind-mount it read-only for the tokenizer, so the split is read for `staff`, write for the runtime alone. `OLLAMA_MODELS_HOST_PATH` in `.env` must name that path or exact counting silently falls back to the character estimate. MLX and the four other LaunchDaemons still run as the operator.

**They are not the only native processes, and the third is easy to forget because it is not a runtime.** `launchd/host-metrics.py` serves free memory, disk, uptime and load on `127.0.0.1:9101` for the host status card, and it exists for the same reason as the two above: a container on macOS reads the Linux VM's memory and the VM's disk, and those numbers are plausible and wrong. Anything that enumerates what runs on the host — the health daemon's checks, the LaunchDaemon install list in the first-deploy runbook — has to count three, not two.

**Observability runs as two containers.** Prometheus scrapes the three applications' `/metrics` and Grafana reads Prometheus. Prometheus is on internal-only networks and publishes no host port. Grafana binds `127.0.0.1:3002`, exposed to the tailnet through `tailscale serve --https 8443` for operators, and therefore cannot be internal-only: Docker will not publish a host port into an `internal` network, so Grafana carries a dedicated non-internal `viz-ingress` alongside its internal link to Prometheus (§6 of security.md explains the trade and why Prometheus is deliberately not given the same). Neither is reachable from the public entrance. See [security.md](../security.md) §6.
