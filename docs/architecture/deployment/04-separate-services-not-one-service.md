# 4. The Critical Design Point: Separate Services, Not One Service With Two Ports

[← Deployment Topology](../deployment.md)

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
[security.md](../security.md) §3.2.

`--host 0.0.0.0` here is correct and does not contradict [security.md](../security.md) §3.3. That rule governs the **host side** of a published port (the left of the colon). Inside a container, binding all interfaces is required for the published port to reach the process. The two are frequently conflated.
