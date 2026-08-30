# 14. Pre-Launch Checklist

[← Security Architecture and Threat Model](../security.md)

```
--- Network ---
[ ] Search the Compose files: no port published on 0.0.0.0 or with a bare "port:port"
[ ] Compare requested against actual bindings, not just the Compose declaration: every
    container's HostConfig.PortBindings has a matching non-empty NetworkSettings.Ports.
    An empty [] means the bind failed and Docker did not retry; the container still runs
    and reports healthy. Grafana's port had never bound once, and a reboot silently
    dropped three more. `docker compose ps` shows none of this. (deployment.md §9)
[ ] Scan the Mac Studio from outside the tailnet: no open ports
[ ] Tailscale ACL applied; verify a plain member cannot reach 8000/8002 directly
[ ] Verify uvicorn binds 0.0.0.0 inside containers (published ports otherwise forward nowhere)
[ ] Prometheus publishes no host port; /metrics is not in any nginx location, so it is unreachable through the proxy
[ ] GET /metrics without the bearer token returns 404 on all three apps; with the token, 200

--- Dual entrance, the easiest thing to get wrong; test each one ---
[ ] 8001 and 8002 are separate ASGI apps on separate sockets with separate middleware
[ ] Send a forged Tailscale-User-Login to the public entrance: stripped, no access granted
[ ] Unauthenticated requests to /admin/* on the public entrance are rejected
[ ] CSRF: a cross-site POST without the token header is rejected
[ ] Forge X-Forwarded-For from an untrusted peer: rejected
[ ] Sign in as a `user` role account: admin functions are genuinely unavailable
[ ] BOOTSTRAP_ADMIN_LOGIN does nothing once users exist, and nothing via the public entrance

--- Local credentials ---
[ ] No account can reach an authenticated state without TOTP enrolled
[ ] Replay the same TOTP code twice: the second attempt is rejected
[ ] Unknown login and wrong password are indistinguishable in response and timing
[ ] Repeated failures slow down and alert, without hard-locking a real account
[ ] Session id changes on login; changing a password kills other sessions
[ ] An invitation link works once, expires, and cannot be replayed after consumption
[ ] Recovery codes are single use and shown only at enrolment

--- Data plane ---
[ ] Country filter active on both the gateway and the public admin entrance
[ ] Per-key CIDR allowlist verified
[ ] API key expiry is mandatory; revocation takes effect immediately
[ ] Gateway serves no /docs or /openapi.json; debug=False
[ ] Guardrails verified in practice: concurrency cap, max_tokens, context bound, per-read timeout, wall-clock generation deadline, disconnect cancels generation
[ ] Send an oversized body with NO credential to /v1/chat/completions: 413 request_too_large,
    not 401 and not 422. A 422 means the body was parsed before the key was checked, which
    is the state found on 2026-08-07; a 401 means it was read in full and then refused.
    Test it malformed as well as well-formed — parseability, not size, is what exposed the
    ordering. Repeat against the admin entrances above their nginx limit (§4.3)
[ ] nginx has proxy_buffering off; confirm streaming is not buffered
[ ] Health endpoints reachable without authentication and leak no version or model information

--- Runtime and secrets ---
[x] Ollama bound to 127.0.0.1 and running as a dedicated service account (`_rcslollama`, 2026-08-18)
[ ] Model reference validation active; no shell=True anywhere
[ ] Database accounts separated; gateway cannot write api_keys or users
[ ] Secrets mounted as files, not environment variables
[ ] metrics_scrape_token and grafana_admin_password are real values, not the shipped placeholders
[ ] .env untracked; gitleaks enabled
[ ] AUTH_MODE=dev fails to start under ENV=production (test it, do not assume)

--- Data and operations ---
[ ] Grafana: admin password replaced, anonymous access off, self-registration off; reachable only via `tailscale serve`
[ ] Full prompt logging disabled by default
[ ] Backups encrypted and a restore actually rehearsed
[ ] FileVault enabled; authrestart verified and documented in the runbook
    (deliberately deferred until the UPS lands; §15.6 carries the interim controls)
[ ] Confirmed with the proxy administrator: no request body logging, no Lua interception

--- Unattended recovery and alerting ---
[x] runbooks/first-deploy.md §1.1 round one has passed with the full check run, not just SSH
    — five passes on 2026-07-26 (17:21, 18:08, 19:43, 20:24, 20:29) out of six attempts; the
    first, 16:45, is the failure the reconciler was written for. The 21:02 injected boot is
    not counted: it was deliberately made to fail and then recovered, which is §1.1a's claim,
    not round one's. This covers round one only — round two, the system update reboot, has
    been run once and failed, so "this machine recovers unattended" as a whole is not
    established. See §1.1's "both rounds" sentence
[x] The reconcile log has shown `OK: all bindings restored` at least once; `intact` is the
    race not firing, which is luck rather than proof that the repair works (deployment.md §9).
    Seven boots all came out `intact` and the margin measurements made rebooting for it a
    bad bet, so the fault was injected instead, per runbook §1.1a: 2026-07-26 21:05:31,
    three dropped bindings detected and recreated at boot. Checked with the qualification
    that it was manufactured, not awaited — the race occurring unaided is a separate claim,
    evidenced only by the 16:45 failure. ("Rebooting *cannot* produce it" was the wording
    here and it was too strong: the 21:51 boot measured an 11-second address where the
    argument assumed a constant 9, so the margin distribution is wider than it looked —
    deployment.md §9. A bad bet, not an impossibility)
[x] The reconciler's container bring-up path has run at boot — 2026-07-26 21:52:14, from
    `not running:` all nine to the whole platform up 51 seconds into the boot. §1.1a's
    injector cannot reach it — it withholds the address, not Docker Desktop's restore — so
    runbook §1.1b injected it the other way, by stopping the stack before the reboot and
    letting `restart: unless-stopped` keep it stopped, which it did completely: Docker
    restored none of the nine. Checked with the same qualification as the row above — the
    state was manufactured, not awaited. Docker Desktop's restore failing *unaided* remains
    evidenced only by the 19:10 boot, whose cause is still unknown
[ ] The health daemon mails: run check-platform-health.sh by hand once with the credentials
    in place and confirm the mail arrives, because the mail path is the one part of the
    monitor that cannot be verified by watching it work
[ ] The alert is not filtered into spam and the daily heartbeat is not muted; the design
    makes an absent mail the signal, so a filtered heartbeat silently removes the alarm
[ ] /opt/homebrew/var/nexus-health.state has an mtime within the last five minutes. The
    log is events-only and is empty both when nothing is wrong and when nothing ran.
    This is readable at any time, including immediately after a boot, only because the
    plist is RunAtLoad and the boot-grace path rewrites the file without checking anything;
    before that fix the criterion was false for the first five minutes of every boot.
    Confirmed at the 2026-07-26 21:02 boot — but not by this file, whose mtime cannot tell
    the two designs apart. Use the unified log instead, and read run duration: the boot-time
    grace run is ~117ms against 528-608ms for a full check (runbook §1.1)
```
