# 7. Resolving the Real Client Address

[← Deployment Architecture](../deployment.md)

Behind the proxy, the true source is in `X-Forwarded-For`. The obvious implementation does not work here, and getting this wrong disables both the country filter and per-key CIDR allowlists.

**Why peer-IP comparison fails.** A natural approach is to check that the connecting peer is the proxy's tailnet address. Under Docker this never matches: traffic arriving through a published port is NAT'd, so the container observes the bridge gateway address (`192.168.65.x` or `172.x.0.1`), never `100.x.x.x`. The same problem breaks a naive "must come from `127.0.0.1`" check on the tailnet entrance. Both would fail closed on every request.

**What actually establishes trust** is the combination of socket binding and the tailnet ACL:

- The gateway publishes only on `${TAILNET_IP}:8000`, so it is unreachable from the LAN or the internet.
- The ACL permits only `tag:ntnu-proxy` to reach that port ([security.md](../security.md) §3.4), so no other tailnet member can connect either.
- Therefore anything arriving at the gateway process came through openresty.

A shared secret header is added as a second, independent layer, since the ACL is otherwise the sole control:

```python
# interfaces/http/middleware/client_ip.py
def resolve_client_ip(request: Request, settings: Settings) -> IPv4Address | IPv6Address:
    """Establish the caller address behind the reverse proxy.

    Trust does not come from the peer address: Docker NAT rewrites it. It comes
    from socket binding (tailnet-only publish) plus the tailnet ACL, with this
    shared-secret header as an independent second check.
    """
    if not compare_digest(request.headers.get("X-Nexus-Proxy", ""), settings.proxy_secret):
        raise UntrustedProxyError()

    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        raise UntrustedProxyError()          # never silently fall back to the peer address
    return ip_address(forwarded.split(",")[0].strip())
```

**This depends on nginx overwriting, not appending.** §5 uses `proxy_set_header X-Forwarded-For $remote_addr`, which replaces the header, so the first value is the real client. The conventional `$proxy_add_x_forwarded_for` **appends** to whatever the client sent, and a caller can then prepend arbitrary values. If the proxy configuration is ever changed to the conventional form, this parser must change to read the **last** value instead. The coupling is easy to break by tidying the nginx config, so it is recorded in both places.
