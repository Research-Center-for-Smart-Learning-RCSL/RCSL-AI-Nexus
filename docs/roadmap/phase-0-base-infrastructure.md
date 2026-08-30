# Phase 0: Base Infrastructure (on the Mac Studio, mostly outside this repository)

[← the roadmap](../ROADMAP.md)

- SSH and Tailscale
- Docker Desktop or an equivalent
- Unified directory layout: `/models`, `/data`, `/logs`, `/config`
- **Model runtimes installed natively on macOS**, not in Docker. Ollama under launchd, `OLLAMA_HOST=127.0.0.1`, running as a dedicated service account. Docker on macOS cannot reach the GPU, so a containerised runtime would be CPU-only and MLX would not run at all. See [ARCHITECTURE.md](../ARCHITECTURE.md) §0.1
- Everything else managed by Docker Compose
