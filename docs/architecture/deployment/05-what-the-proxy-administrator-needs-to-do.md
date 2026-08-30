# 5. What the Proxy Administrator Needs to Do

[← Deployment Architecture](../deployment.md)

Four items, none large:

1. **Install Tailscale and join the tailnet**, tagged `tag:ntnu-proxy` so the ACL can restrict it to the three ports it needs ([security.md](../security.md) §3.4).
2. **Add two nginx server blocks** (below).
3. **Serve a certificate for each name.** Both are single-label, so an existing `*.rcsl.online` wildcard covers them and no issuance may be needed at all — point the server blocks at it. This is new since the rename: the previous two-label names were outside a TLS wildcard's one-label match and each needed its own certificate. If there is no usable wildcard, issue per-name certificates; port 80 is already open, so HTTP-01 validation works directly.
4. **Confirm nginx does not log request bodies** and that no Lua script intercepts these paths. Bodies are not logged by default; this is a confirmation, not a change.

### The one way this goes wrong, found on the first real attempt

**Every `proxy_set_header` below must end up inside the `location` block that actually serves the request.** nginx inherits them all-or-nothing: a level inherits the set from above *only if it declares none of its own*, so a single `proxy_set_header` in a `location` silently discards every one inherited from the `server` block. There is no warning, `nginx -t` passes, and the configuration file reads exactly as intended.

This is not hypothetical. On 2026-08-03 the administrator entered the directives into Nginx Proxy Manager's **Custom Nginx Configuration** field, which is inserted at *server* level, while NPM's generated `location /` carries its own `proxy_set_header` set — so all four of ours were dropped. Both header controls failed at once and nothing upstream showed it: `client_max_body_size`, `proxy_buffering` and `proxy_read_timeout` are not `proxy_set_header` and inherit normally, so everything else behaved. See [PROGRESS.md](../../PROGRESS.md) 2026-08-03.

Three consequences worth carrying:

- **Verify with `nginx -T`, not the file or the UI.** It prints the configuration nginx actually loaded. The check is whether the lines appear *inside* `location`, not whether they appear.
- **A hand-written `location` must re-declare what the generated one had.** The same rule applies in reverse: such a block discards the proxy's own `Host`, `X-Forwarded-Proto`, `Upgrade` and `Connection`. Copy them out of `nginx -T` rather than from memory. This platform reads neither `Host` nor `X-Forwarded-Proto`, so those two cost nothing here, but `Upgrade`/`Connection` are what a websocket support toggle exists to set.
- **`X-Forwarded-For` is replaced, never added alongside.** nginx does not de-duplicate `proxy_set_header`; declaring it twice sends the header twice, and `client_ip.py` reads the *first* value, so leaving the proxy's own `$proxy_add_x_forwarded_for` next to ours restores the defect it was written to fix.

`scripts/verify-public-entrance.sh` tests all of this from outside and distinguishes "no header set" from "wrong value set", which look identical from a single probe.

### nginx configuration

```nginx
# http level. The zone the management block's limit_req names below; without
# it nginx refuses to load the configuration with "unknown limit_req zone".
# Referenced here since this section was written and defined nowhere until
# 2026-08-03, so the template as published could not start.
limit_req_zone $binary_remote_addr zone=admin_login:10m rate=10r/m;

# Redirect plain HTTP for both hostnames, leaving the ACME path reachable
server {
    listen 80;
    server_name llm.rcsl.online llmapi.rcsl.online;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

# Management UI
server {
    listen 443 ssl;
    http2 on;
    server_name llm.rcsl.online;

    # Per-name paths shown for concreteness. A `*.rcsl.online` wildcard covers
    # this name — both are single-label — so pointing both blocks at the
    # wildcard is equally correct and is one fewer renewal to forget.
    ssl_certificate     /etc/letsencrypt/live/llm.rcsl.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/llm.rcsl.online/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;

    # Knowledge base uploads. Deliberately *looser* than the application's own
    # 32 MiB (`domain/services/upload_policy.py`), so ours is the limit that
    # fires and the caller gets an error naming the reason. Set it tighter and
    # nginx rejects the request itself, with its own HTML 413 in place of the
    # upload dialog's message. Entered as 10m on the first attempt.
    client_max_body_size 64m;

    limit_req zone=admin_login burst=10 nodelay;

    location / {
        proxy_pass http://TAILNET_IP:3001;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Nexus-Proxy     "<shared-secret>";

        # Identity headers may only originate from tailscale serve.
        # The application strips them too; this is the outer layer.
        proxy_set_header Tailscale-User-Login "";
        proxy_set_header Tailscale-User-Name  "";

        # The admin chat endpoint streams
        proxy_buffering    off;
        proxy_read_timeout 3600s;
        proxy_http_version 1.1;
    }
}

# Inference API
server {
    listen 443 ssl;
    http2 on;
    server_name llmapi.rcsl.online;

    ssl_certificate     /etc/letsencrypt/live/llmapi.rcsl.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/llmapi.rcsl.online/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;

    client_max_body_size 10m;

    location / {
        proxy_pass http://TAILNET_IP:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Nexus-Proxy     "<shared-secret>";

        proxy_set_header Tailscale-User-Login "";
        proxy_set_header Tailscale-User-Name  "";

        # Required for SSE. Without these, streamed output is buffered until
        # the response completes and appears to users as "the model is slow".
        #
        # `3600s` is the target; the machine currently runs `86400s` on both
        # hosts (confirmed by `nginx -T`, 2026-08-09) and nothing is waiting on
        # the difference. Stated here because a template that silently disagrees
        # with the deployment is how `300s` survived in ROADMAP.md for two days
        # after the real value had been read.
        proxy_buffering    off;
        proxy_read_timeout 3600s;
        proxy_http_version 1.1;
    }
}
```

`proxy_buffering off` and `proxy_read_timeout` must be communicated explicitly. Without them, streaming output is withheld until generation finishes, which presents as a slow model and wastes considerable debugging time on the wrong layer.

**`proxy_read_timeout` was `300s` here until 2026-08-07, and that number became wrong without anyone touching it.** It bounds the gap between reads, and **prompt evaluation produces no bytes at all** — so the longest legitimate silence is a full context being read. `config.py` put that at `98304 / 105.5 = 932` seconds against the platform's own 1200-second per-read ceiling (`65536 / 117.9 = 556` against 600 until 2026-08-14); on the ceiling and the model in force today it is `122880 / 711 = 173` seconds, because 105.5 tok/s was the dense model's and that model now serves nothing (re-measured 2026-08-17 — see the `MAX_CONTEXT_LENGTH` row in §10). Every figure in the next three paragraphs is the 2026-08-14 one it was written against, and is kept because the reasoning is what they are here for. `300s` cut the 556 in force that day roughly in half, and the cut arrives as a reset with nothing in any application log, which is the failure mode this whole section exists to avoid.

It was correct when written: `MAX_CONTEXT_LENGTH` was 32768, so the worst silence was 278 seconds and fit inside 300. **The ceiling doubled on 2026-08-05 and this file was not one of the places that got updated.** `config.py` already says those values "are one decision and have to be changed together" and names two readers; nginx is the third, and it is the one nobody can see from the repository.

**What is actually running is `86400s` on both hosts, confirmed by `nginx -T` on 2026-08-09.** This section did not say so until that day, and the reading is not new — `llmapi`'s value was read on 2026-08-07 and recorded in [PROGRESS.md](../../PROGRESS.md); it simply never reached [ROADMAP.md](../../ROADMAP.md), which went on saying `300s`. The 2026-08-09 run settled it against the running configuration rather than against either file:

| | `llm.rcsl.online` | `llmapi.rcsl.online` |
|---|---|---|
| `proxy_read_timeout` | `86400s` | `86400s` |
| `proxy_buffering` | `off` | `off` |
| `client_max_body_size` | `64m` — matches this section | `512m` — this section says `10m` |
| defined in | `data/nginx/custom/http.conf` | `data/nginx/custom/http.conf` |

**Three things that were open closed with the same command.** `proxy_buffering off` is confirmed live on both hosts for the first time. `server_name llmapi.rcsl.online` appears exactly once and `nginx -t` reports no `conflicting server name`, so the duplicate-block repair of 2026-08-07 holds and has not regressed — previously unverifiable from outside. And **the management host's directives had never been read at all**; they are now known rather than assumed, which was the last place in this section where a value was being taken on trust. The timeout defect this section spent three paragraphs deriving **was real against the specification and had never once been real in the deployment** — the same duplicate-server-block story as the headers, one file further on. Read the derivation above as the reasoning for a target, not as a description of a fault.

**The remaining case is for lowering it, and it is weak on purpose.** A day is generous to the point of not being a backstop: `proxy_read_timeout` is what reclaims a connection from an upstream that has genuinely hung, and nginx worker connections are finite, so an effectively unbounded value turns a hang into pinned connections. `3600s` restores that property while staying far above anything legitimate. **The comparison to make is against another between-reads bound, not against a whole-request one**: `proxy_read_timeout` limits the gap between bytes, so its counterpart is `REQUEST_TIMEOUT_SECONDS` (1200 since 2026-08-14), inside which the longest honest silence — a full `MAX_CONTEXT_LENGTH` prompt, `98304 / 105.5 = 932` seconds when this was written and `122880 / 711 = 173` on the current ceiling and model — already has to fit. **`3600s` still clears that with room, so this change needed nothing from the proxy administrator** — which is the point of having sized it against the class of bound rather than against the number. The 2100-second figure below is the sum of that and the generation deadline, which is a budget for a whole request and bounds nothing about a single gap; setting them side by side is the same conflation this section warns about two paragraphs up. **Nothing user-visible is waiting on this**, and whoever is asked should be told that; an urgent-sounding request for a change with no symptom behind it spends credibility that the next real one will need.

**A note on how the wrong number survived.** `1560s` was derived from the platform's own limits, and the 2026-08-09 revision proposed `3600s` derived instead from the model's architectural maximum — `262144 / 117.9 = 2224` seconds — on the reasoning that a bound fitted to a tunable expires whenever the tunable moves. That reasoning is worth keeping for choosing a target, with one qualification it did not carry: **2224 seconds is not a silence this deployment can currently produce**, because `MAX_CONTEXT_LENGTH` refuses a prompt that large with a `413` and `REQUEST_TIMEOUT_SECONDS` would cut the gap at 1200 anyway (600 on the day this was written; the raise landed 2026-08-14). It is the bound that survives *changing* those two, which is a different and much weaker claim than the one it was written as. What the revision did not do, and what mattered more than any of this, was check whether the value being "corrected" was the value in force. **It was not, and this repository already knew: the reading was in `PROGRESS.md` and had never been propagated to `ROADMAP.md`, which is the direction `PROGRESS.md`'s own header says to distrust.** Deriving a number more rigorously is worth nothing next to reading the one that is live.

**The management host reads `86400s` and `64m`**, the latter exactly as specified above. Its value could not have been learned from outside in any case: the frontend's own `experimental.proxyTimeout` (`next.config.js`, 2,160,000 ms — thirty-six minutes, raised with the read timeout on 2026-08-14 and 1,560,000 when this was written) sits in front of it and cuts a stalled request first, which is the inner limit firing and is correct. Reading the file was the only way, and it took one command.
