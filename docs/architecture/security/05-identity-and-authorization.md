# 5. Identity and Authorization

[← Security Architecture and Threat Model](../security.md)

### 5.1 Management UI: Two Entrances, Two Authentication Schemes

Port and topology detail in [deployment.md](../deployment.md) §4.

**Entrance one: tailnet, for daily use.** `tailscale serve` injects identity headers:

```
Tailscale-User-Login: you@example.com
Tailscale-User-Name: Your Name
```

No password, no stealable session token, no password reset flow to protect. Removing someone from the tailnet revokes access immediately.

**Entrance two: public, for people without Tailscale.** Arrives through openresty and authenticates with an **invitation-only local account: password plus mandatory TOTP**. Accounts cannot be self-registered; an administrator creates them. Authentication is implemented inside the admin application, so nothing about it depends on an externally maintained nginx configuration or on a third-party identity provider.

Choosing local credentials over an external identity provider trades a one-time integration for permanently owned security work: password storage, reset flows, lockout behaviour, and second-factor handling all become this project's responsibility. That trade is accepted deliberately, in exchange for having no external dependency and no account existing that an administrator did not create. **Mandatory TOTP is what makes it acceptable**; a single password guarding a control plane whose worst case is host code execution would not be.

**Common rules**

- Passing authentication means "may enter", **not "is an admin"**. Identity is always resolved against the `users` table, and roles are owned by the platform.
- A user record may carry a Tailscale login, local credentials, or both. Someone who only ever uses the tailnet never needs a password; someone who needs the public entrance is issued an invitation. Both map to one record and one role.

**The most dangerous possible error: sharing one listening socket between the entrances.**

If both entrances served from the same port, anyone on the internet could send a forged `Tailscale-User-Login: admin@example.com` header and bypass the password and TOTP entirely, gaining administrator access.

Therefore:

- The entrances are **separate ASGI applications on separate sockets**, each with its own authentication middleware, rather than one application branching on request properties.
- The public application **unconditionally strips every `Tailscale-*` header**, no matter how plausible.
- openresty clears the same headers as a second layer ([deployment.md](../deployment.md) §5).

This is the same reasoning as §1: **isolation is guaranteed by socket binding, not by string comparison.**

### 5.2 Roles and Where Authorization Lives

| Role | Permissions | Deliberately cannot |
|---|---|---|
| `admin` | Everything, across every tenant | — |
| `tenant_admin` | Its own tenant's people, API keys and knowledge base; reads the fleet | Create a tenant, or change models, nodes or routing |
| `operator` | Model lifecycle, nodes, routing policies, all usage and logs | Invite users, change roles, or issue a key for anyone else |
| `curator` | Read and write the knowledge base and the prompt templates | Anything outside it |
| `auditor` | Read everything — usage, logs, models, nodes, users, tenants | Write anything at all, including their own API keys |
| `user` | Use the chat UI, manage their own API keys, view their own usage, read their tenant's prompt templates | Read the model registry or the node addresses; author a prompt template |

`service` is the seventh entry in the enum and is not in this table: it belongs to an API key, never a person, and holds `chat:use` and `usage:read_own` whatever capability list the key was issued with.

"View their own usage" became true on 2026-08-04 and was a description of an intention before that. `usage:read_own` was granted from the beginning and **required by nothing**: every usage read demanded `usage:read_all`, so the row in this table named a permission with nowhere to spend it. `GET /admin/usage/me` now answers it, attributed by actor rather than by key, so it covers every key an account holds and its admin-chat traffic alike ([PROGRESS.md](../../PROGRESS.md) 2026-08-04). A granted scope that no code path requires is worth looking for elsewhere: it reads as a capability in every review and is not one.

**These do not nest.** A `curator` may rewrite the knowledge base that an `operator` cannot touch; an `operator` may restart a node that a `tenant_admin` cannot. The only ordering that holds is that `admin` is a superset of all of them, so nothing in the UI or the backend may compare two roles for seniority.

**The tenant boundary is not a role.** It is structural: `di.py` builds `ManageUsers` and its neighbours with a tenant-scoped repository, so `user:write` reaches only the caller's own tenant whoever holds it. That is why `tenant_admin` is an ordinary role rather than a second dimension — the only powers that cross tenants are the platform-global ones (tenants, nodes, models, routing), and it simply lacks their write scopes.

**A role may be granted only by an account that already holds everything it confers.** `USER_WRITE` says an account may be created or edited, not with which role, and nothing enforced the difference until 2026-08-04 — so a `tenant_admin` could invite an `admin`, take the single-use onboarding link from the same response, and hold every scope a minute later, including the `TENANT_WRITE` this table says it cannot have. `domain/services/grantable_roles.py` is the whole rule; it needs no table of its own and stays true for roles added later. In practice `tenant_admin` may staff its own tenant (`curator`, `auditor`, `user`, itself) and may not reach `operator` or `admin`.

**Two invariants are enforced by `tests/unit/test_role_scopes.py` rather than by review.** `_ADMIN_SCOPES` is `frozenset(Scope)`, so a scope added later reaches `admin` automatically and no other role — which is how the roles above would quietly rot, a new feature at a time. The test requires every scope to reach some non-`admin` role, or to be listed in `ADMIN_ONLY_SCOPES` with its reason. **Three are listed**, and this paragraph named only the first until 2026-08-18 while §12.1 and §7.4 argued the other two. `tenant:write`, because a tenant is the boundary the others are confined by, so granting the power to draw one is granting the power to step outside it. `retention:write` since 2026-08-04, because held by a `tenant_admin` it would let them erase the record of what they did inside the tenant they administer (§12.1). And `prompt_log:read` since 2026-08-08, the mirror of it: the tenant boundary confines every other authority that role holds and offers the tenant's own members no protection from the person administering them (§7.4).

**The chat UI is served by the admin API (`/admin/chat`), not the public gateway.** It reuses the same `RouteChatRequest` use case but authorizes by user identity rather than an API key, so operators need not mint keys for themselves and internal traffic is not subject to the public geo and CIDR restrictions. The §4.3 resource guardrails still apply, because they protect the hardware rather than the perimeter.

Authorization is enforced in `application/use_cases`, not in the domain (which should not know who is calling) and not in routers (where a second entrance to the same use case would eventually miss the check). Each use case declares its required scope; `AuthorizationPort` and `AuditPort` are domain ports so that "authorized and audited" is structural. See [backend.md](../backend.md) §7.

UI-level role gating is a usability affordance only. It gates on the **scope**, not the role: `GET /admin/me` returns the caller's resolved scope list and the frontend asks `can('model:write')` rather than "is this an administrator". That question had two answers in forty-five places, which was right while there were two roles and wrong the moment there were six — it would have hidden the Models screen from the `operator` whose whole job it is. The server checks the same scopes on arrival regardless, so this remains an affordance.

### 5.3 Local Credentials, TOTP, and Sessions

**Password storage.** argon2id through a `PasswordHasherPort`, so parameters are tuned in one adapter and the domain never imports a hashing library. Minimum length 12, strength checked with zxcvbn, and no composition rules (which push users toward predictable substitutions without adding entropy). Passwords are never logged, never returned by any endpoint, and never transmitted by the platform; see §5.4.

**TOTP is mandatory, not optional.** RFC 6238, 30-second step, 6 digits, accepting one step of clock skew either side. Three details that are easy to omit and each defeat the point:

- **Replay prevention.** The last accepted time counter is stored per user and a code from that counter or earlier is rejected. Without this, a code observed over the shoulder or in a phishing proxy remains valid for its whole window.
- **Recovery codes.** Ten single-use codes, hashed at rest, displayed exactly once at enrolment. Without them, a lost phone means an administrator must reset the account manually, and in the worst case nobody can reach the platform at all.
- **The secret is a bearer credential.** It is encrypted at rest, never returned after enrolment, and never written to logs.

Enrolment happens during invitation acceptance and cannot be deferred, so an account never exists in a password-only state.

**Login flow and abuse resistance.** Password verification and TOTP verification are separate steps, and both are rate limited.

- **No user enumeration.** An unknown login and a wrong password produce the same response and comparable timing; the handler runs a dummy hash for unknown accounts rather than returning early.
- **Rate limiting by source address and by account**, with increasing delay. Hard account lockout is deliberately avoided: it converts a known login into a denial-of-service lever against a real person. Escalating delay plus alerting achieves the defensive goal without that side effect.
- **Every attempt is written to the audit log, and the limiter firing is written too** — `user.signed_in`, `user.sign_in_failed` with the reason the response deliberately withholds, `user.sign_in_throttled`, `user.recovery_code_used`, `user.signed_out`. Each failure path records exactly once, on the same side of the same work, because a database round trip on some paths and not others would be the timing oracle `dummy_verify` exists to prevent. **The throttle record is the deliberate exception: once per address per window, not once per refusal.** A refused request costs the caller nothing — the check runs before the hash and the refused path records no failure, so the counter stays above its ceiling for the full window — and a row per refusal would hand whoever is already being refused an unauthenticated INSERT per request, into an append-only table kept for a year. A limiter that sheds CPU while adding a write is inverted. **Alert *delivery* is not built**: these rows are the queryable substrate an alert rule would read, and the rule itself is the §13 Phase 3 item. Until 2026-08-02 this bullet claimed both halves in the present tense and neither existed — `AuthenticateLocal` took no `AuditPort` at all.
- **A login that is not address-shaped is recorded as a digest, not verbatim.** Logins are `EmailStr` at creation, so a presented string with no `@` in it is most often someone typing their password into the login field — and `actor_display` is kept for a year and readable with `logs:read`. The digest keeps repeats grouping and lets a suspected value be confirmed by hashing it. `LoginThrottle` already digests the login so its counters cannot accumulate a list of valid addresses; this is the same rule one table over.
- §4.1(a) applies to this entrance as well, so most unsolicited attempts never reach the handler.

**Sessions.** Server-side in Redis under an opaque identifier. Cookie uses the `__Host-` prefix with `HttpOnly`, `Secure`, `SameSite=Lax`, and no `Domain` attribute. Absolute lifetime (for example 12 hours) plus an idle timeout; `/admin/me` returns `session_expires_at` so the UI can warn before expiry. A new session identifier is issued on successful login to prevent session fixation, and **changing a password invalidates every other session** for that user.

**CSRF.** The public entrance authenticates with a cookie, so state-changing requests need protection. `SameSite=Lax` alone is insufficient because it still permits top-level POST navigations. A double-submit token is used: a random value in a non-`HttpOnly` companion cookie must be echoed in a request header on every non-GET request, and the API client attaches it automatically ([frontend.md](../frontend.md) §3).

**Both entrances install it, and this paragraph claimed otherwise until 2026-08-05** — while §13.0 below correctly recorded "CSRF double-submit on both admin entrances", so the document disagreed with itself on a control. The retired claim was that the tailnet entrance needs no protection, having no ambient credential. It has one: identity arrives in a header rather than a cookie, and a hostile page indeed cannot add a header — but it does not have to, because `tailscale serve` attaches it to any request leaving that device, including one provoked from the browser of somebody signed in to the tailnet. A header injected by the proxy is as ambient as a cookie attached by the browser. On that premise a body-less POST — revoke a key, unload a model, start a download, invalidate an invitation — was cross-site reachable there until commit `ec56046` on 2026-07-25. The premise itself survived in `csrf.py`'s docstring and here for another eleven days, which is its own lesson: a fix that does not reach the explanation leaves the next reader the same reasoning to be wrong from.

### 5.4 Invitations and Password Reset

**The platform never transmits a credential.** Account creation issues a single-use invitation link; the administrator delivers it out of band by whatever channel is appropriate. The recipient then chooses their own password and enrols TOTP in one flow.

```
admin creates user (login + role, no credentials)
  -> system generates a 256-bit invitation token, stores only its hash, 72 hour expiry
  -> admin copies the link and delivers it out of band
  -> recipient sets a password, enrols TOTP, receives recovery codes
  -> token marked consumed, cannot be reused
```

This avoids sending a password over email, avoids a temporary-password state that people forget to change, and removes any SMTP dependency from Phase 1. Password reset works the same way: an administrator issues a reset link, which invalidates the existing password and all active sessions on use.

Invitation and reset tokens are stored hashed, are single use, expire, and their issue and consumption are audited. The residual risk is the out-of-band delivery channel, which is recorded in the threat model; keeping the expiry short limits the window.

Self-service reset by email can be added later once an `EmailPort` exists, but it is not needed at this team size and would add a delivery dependency and a new enumeration surface.

### 5.5 Bootstrapping the First Administrator

A fresh deployment has an empty `users` table, so every authenticated identity resolves to an unknown role and nobody can reach the management UI, including the person who deployed it.

The bootstrap rule:

- `BOOTSTRAP_ADMIN_LOGIN` names one Tailscale login.
- It takes effect **only while the `users` table is empty**, and **only through the tailnet entrance**.
- The first matching login creates a single `admin` user, after which the setting is inert.

That user is created **without local credentials**, since the tailnet entrance does not use them. If they later need the public entrance, they issue themselves an invitation through the normal flow in §5.4.

Restricting bootstrap to the tailnet entrance matters: were it available publicly, an attacker who reached a freshly deployed instance before its operator could claim administrator rights. The event is written to the audit log.
