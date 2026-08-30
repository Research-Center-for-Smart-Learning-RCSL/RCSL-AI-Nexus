# 8. Migration Path

[← Deployment Topology](../deployment.md)

The topology is deliberately reversible:

- Moving `rcsl.online` DNS to Cloudflare later means pointing `llmapi` at a Tunnel. No application code changes, and traffic no longer transits a third party, resolving [security.md](../security.md) §15.1.
- Adding a second compute node leaves the entrance unchanged; only the gateway's routing targets grow.
- Dropping the dependency on the proxy host means disabling the public admin entrance; the tailnet entrance is unaffected.
