# 6. What Is Lost Without a CDN, and Who Covers It

[← Deployment Topology](../deployment.md)

| Previously from a CDN | Now |
|---|---|
| Country filter | **In the application**, MaxMind GeoLite2, on both the gateway and the public admin entrance |
| Rate limiting | Per-key limits in the application, plus `limit_req` at nginx |
| DDoS mitigation | None. Campus network only |
| WAF | None. Application input validation only |
| Origin IP concealment | Already achieved; only the NTNU host is exposed |

**Therefore [security.md](../security.md) §4.3 resource guardrails are promoted from recommended to the only line of defence.** Every request now reaches the Mac Studio. Without a concurrency cap, a `max_tokens` ceiling, timeouts, and disconnect cancellation, a single abusive caller can make the machine unresponsive.
