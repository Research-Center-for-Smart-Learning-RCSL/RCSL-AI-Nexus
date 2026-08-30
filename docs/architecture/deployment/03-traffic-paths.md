# 3. Traffic Paths

[← Deployment Architecture](../deployment.md)

```
Control plane, entrance 1 (tailnet, everyday use)
  browser --tailnet--> tailscale serve --> 127.0.0.1:3000 --> frontend-tailnet
                                                                  |  /admin/* rewrite
                                                                  v
                                                             admin-tailnet:8001
                                                    trusts Tailscale-User-Login, no password

Control plane, entrance 2 (public, for people without Tailscale)
  browser --public--> openresty --tailnet--> TAILNET_IP:3001 --> frontend-public
       llm.rcsl.online                                          |  /admin/* rewrite
                                                                     v
                                                                admin-public:8002
                                          password + TOTP session; strips every Tailscale-* header

Data plane
  external service --public--> openresty --tailnet--> TAILNET_IP:8000 --> gateway
        llmapi.rcsl.online                                              API key auth
```

API calls are same-origin through the Next.js rewrite, which avoids CORS and third-party cookie problems entirely. See [frontend.md](../frontend.md) §1.
