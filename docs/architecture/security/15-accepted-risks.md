# 15. Accepted Risks

[← Security Architecture and Threat Model](../security.md)

Recorded explicitly so they are not later mistaken for oversights, with the conditions that should trigger reconsideration.

### 15.1 Inference Traffic Passes Through a Third-Party Machine in Plaintext

**Situation.** Public traffic is proxied by the openresty host at NTNU, where TLS terminates. Its administrator is technically able to read traffic passing through, including prompts and completions, which is the team's unpublished research content.

**Why accepted.** Same institution, existing trust relationship. In exchange, no public entrance, certificate workflow, or domain has to be built and maintained.

**An important distinction.** "Able to" is not "does by default". nginx access logs **do not record request bodies**, so POST content does not land in logs automatically. The real risk is active interception (an added Lua script, `tcpdump`, a modified `log_format`), not routine logging. That is why the mitigations below are specific confirmations rather than general appeals to trust.

**Mitigations.**

- Confirm with the administrator: no request body logging, no Lua interception on `/v1/*`.
- Retain full request metadata auditing on the Mac Studio (§12) so records can be reconciled against the proxy's access logs if needed.
- Route particularly sensitive work over the tailnet directly, bypassing the public entrance.

**Reconsider when.**

- Data sensitivity rises (a project involving personal data or IRB-regulated material).
- The machine changes hands or maintainers.
- The machine suffers any security incident.
- `rcsl.online` can move to Cloudflare, at which point Tunnel eliminates this risk entirely ([deployment.md](../deployment.md) §8).

### 15.2 No Edge Protection

**Situation.** Without a CDN there is no WAF, no DDoS mitigation, and no edge rate limiting. All traffic reaches the Mac Studio.

**Mitigation.** The §4.3 resource guardrails are promoted to the only line of defence and must be implemented and tested rather than assumed. The proxy administrator can additionally apply `limit_req` as a coarse filter.

### 15.3 The Country Filter Is Bypassable

**Situation.** Only Taiwan and Australia are permitted, but a VPS or VPN in either country defeats it.

**Why accepted.** Its purpose is noise reduction, not perimeter enforcement. The real defences are API keys and resource guardrails.

### 15.4 Wildcard DNS on a Shared Domain

**Situation.** `*.rcsl.online` resolves every subdomain to the proxy host. Anyone able to obtain a vhost there can serve content under a plausible-looking name, which assists phishing.

**Half of this was closed on 2026-08-04.** The hostnames were `ai.nexus.rcsl.online` and `api.nexus.rcsl.online`, which resolved only by multi-label synthesis and so depended on no one ever creating a `nexus.rcsl.online` node in the zone — a single addition by the domain's administrator, who has no reason to consult this project, would have taken both entrances down at once. `llm.rcsl.online` and `llmapi.rcsl.online` are single-label and carry no such dependency. The rename was cheap because a hostname is not a trust boundary here: the perimeter is the `X-Nexus-Proxy` secret and the client address, neither of which reads the name ([deployment.md](../deployment.md) §2).

**Why the rest is accepted.** The wildcard itself remains, and with it the phishing surface, because the domain is maintained by someone else and the wildcard predates this project. Worth raising with its administrator, and worth requesting explicit A records for the two hostnames this project uses rather than relying on the wildcard at all.

### 15.5 The Gateway Reaching the Tailnet Admin Entrance — Resolved

**What it was.** `gateway` and `admin-tailnet` shared the `app` Compose network. The tailnet entrance binds `0.0.0.0` inside its container and trusts `Tailscale-User-Login` outright, so a process with code execution in the gateway could `curl http://admin-tailnet:8001/...` with a forged identity header and obtain administrator access, with no tailnet and no session. Socket binding isolates the host-published port, not the Docker service name. An adversarial review surfaced it once the tailnet entrance grew from health-only into a full API.

**How it was closed.** The single `app` network was split so that the gateway shares no network with either admin entrance (§3.2). The data plane has its own database segment (`gateway-data`) and its own host-egress network (`gateway-egress`); the control plane has `admin-data` and a per-entrance control network. postgres, redis and qdrant are dual-homed across the two database segments, which is safe because they accept connections and never open one. The invariant is verifiable from `docker compose config`: the intersection of the gateway's networks with each admin entrance's is empty. As a bonus of the same change, `frontend-public` — which faces the internet — can no longer reach `admin-tailnet` either.

**Residual.** None from this vector, and the deeper defence has since landed too: the §6 per-service database credential split is now implemented, so a compromised gateway can neither forge a header to the admin socket (closed here) nor write `api_keys` or `users` directly (denied by its database grants).

### 15.6 FileVault Deferred Until the UPS Lands

**Situation.** The first deployment runs with FileVault off. On Apple Silicon the internal SSD is hardware-encrypted and fused to the Secure Enclave regardless, so the drive cannot be pulled and read elsewhere. What FileVault adds is binding the volume key to a user password. Without it, protection of the data at rest reduces to the macOS login and recoveryOS authentication rather than to cryptography, and the automatic login below removes the first of those.

**Why accepted.** §9.3 argues for keeping FileVault on and that reasoning is unchanged; what changed is the sequencing. FileVault's cost is paid at every cold boot, because the pre-boot unlock needs a person at the machine and until it happens there is no network, no Tailscale, and no SSH, so the deployment cannot be recovered remotely. Two things bound that cost: a UPS, which makes unplanned power loss rare, and `fdesetup authrestart`, which covers planned reboots. The UPS is Phase 3 and does not exist yet. The machine is headless by design ([ARCHITECTURE.md](../../ARCHITECTURE.md): SSH is reserved for repairs), so with no UPS an encrypted disk means every power cut takes the platform down until someone travels to it.

**Compensating controls while it is off.**

- Startup security left at Full Security, with recoveryOS reachable only by administrator authentication, so the machine cannot be booted from external media. Apple Silicon has no separate firmware password; Recovery Lock through MDM is the equivalent where one is available. §11 already requires this control, but with FileVault off it carries weight FileVault would otherwise have carried.
- Physical placement in an access-controlled space, which becomes load-bearing rather than defence in depth.
- Automatic login is enabled, which is what makes unattended reboot work at all. It is only tolerable because the disk is unencrypted anyway. Turning FileVault on later must disable it in the same change, and the FileVault unlock then doubles as the login. **[Updated 2026-09-05]** Docker no longer depends on the login session: Colima runs as a LaunchDaemon (`online.rcsl.colima`) and starts before any user logs in. Automatic login is still needed for other login-session-dependent tasks, but Docker is no longer among them.

**A UPS bounds power loss, not every unplanned reboot.** The reasoning above treats the UPS as the thing that makes cold boots rare, and for power cuts it does. It does nothing for a kernel panic, a watchdog reset, or a failed update: each of those reboots the machine, and with FileVault on each leaves it at the pre-boot unlock screen with no network. So installing the UPS does not by itself restore the property "this machine recovers unattended" — it lowers the frequency of losing it. macOS offers no clean way to have both an encrypted volume and unattended recovery on hardware without out-of-band management, and a Mac Studio has none. Whoever acts on the trigger below should decide with that in view rather than treating the UPS as a full answer.

**This is therefore also a constraint on remote operation, not only on data at rest.** With FileVault on, remote access has no fault tolerance: one unplanned reboot ends it until someone travels to the machine, and that is not a state anything remote can repair. If the platform is to be operated by someone who is not routinely near it, that consideration points the same way the sequencing decision already does, and should be weighed alongside the UPS when the trigger fires.

**Reconsider when.** The UPS is installed. That is the trigger to enable FileVault, verify `authrestart`, disable automatic login, and write the unplanned-power-loss procedure into the operations runbook — bearing in mind the two paragraphs above, since the UPS closes less of the gap than it first appears. Sooner if the platform starts handling personal or IRB-regulated data, where an unencrypted disk in a shared facility stops being acceptable whatever the reboot cost.

**Status.** Acted on 2026-07-26: `sudo fdesetup disable` run on the Mac Studio, `fdesetup status` reports `FileVault is Off`. `fdesetup supportsauthrestart` returned true beforehand, so the `authrestart` path is available whenever FileVault is turned back on. What the machine now holds unencrypted is worth naming plainly, because it is what the compensating controls are carrying: the **sixteen** plaintext credential files under `secrets/`, the TOTP encryption key among them, and whatever research data passes through the platform. Eleven when this paragraph was written on 2026-07-26; the count grew with the deployment, most recently on 2026-07-30 when the MaxMind licence key and Qdrant's two keys landed, and it is the kind of figure that goes stale without anyone deciding it should. The unattended-recovery chain this was done for is recorded in [runbooks/first-deploy.md](../../runbooks/first-deploy.md) §1 together with the acceptance test that is meant to prove it.

**That test has now been run twice: the chain failed round one, was repaired, and passed the re-run.** This matters here specifically, because the whole trade in this section — accept an unencrypted disk in exchange for a machine that recovers by itself — is only worth making if the second half is true. On 2026-07-26 the first reboot brought back automatic login, both LaunchDaemons, Docker Desktop and all nine containers, and still left the platform unreachable: Docker Desktop had bound its published ports before `tailscaled` had the tailnet address up, the binds failed, and nothing retried or restarted. A LaunchDaemon now reconciles that after boot (deployment.md §9), and the re-run later the same day passed every item of §1.1 with all six published ports bound. **[Updated 2026-09-05]** The port binding race is structurally eliminated by the migration to Colima: containers bind to `127.0.0.1` (which always exists), and a socat LaunchDaemon forwards from the tailnet address only after `tailscaled` has it up. The reconciler's other role — bringing up a stack that was not restored — remains necessary under any Docker runtime.

**What that re-run did not do is exercise the repair.** The reconciler ran, found nothing broken, and exited: on that boot `tailscaled` had the address on `utun0` eleven seconds before Docker bound, where on the failing boot it was three seconds late (deployment.md §9 has the measurement and its cause). The margin is what decides it, nothing in the configuration controls the margin, and the daemon that would cover a lost race has still never been through one at boot. So the exchange this section accepts has been received once. "This machine recovers unattended" is an observed property of a single boot rather than a demonstrated one, and it stays that way until §1.1 produces the `OK: all bindings restored` outcome at least once.

### 15.7 The Alerting Credential Is the Operator's Own Mailbox

**Situation.** `launchd/check-platform-health.sh` sends its alerts through Gmail's SMTP, authenticating with a Google app password held in plaintext at `secrets/alert_smtp_password`. The account it authenticates as is `leolove3very@gmail.com`, which is also the recipient, the platform's first administrator (`users`), and the mailbox where password-reset links for everything else would arrive. `secrets/README.md` recommends a dedicated sending account and the deployment did not use one.

**Why accepted.** An app password is materially weaker than the account password in the ways that matter here: it cannot sign in to the web account, cannot change account settings or security options, cannot pass 2-Step Verification, and can be revoked individually without disturbing anything else. What it can do is send and read mail over SMTP and IMAP. That is not nothing — mail access alone is enough to drive a password reset on a third-party service — but the blast radius is a mailbox rather than an identity, and the alternative cost is maintaining a second Google account whose own recovery path then has to be looked after. Sending to oneself also removes a delivery hop and a spam-classification risk that a new, unknown sending address would introduce, which matters because this design makes an *absent* mail the alarm.

**What carries the load.** The same controls §15.6 already names, because this file lives on the same unencrypted disk as the other fifteen: Full Security startup, an access-controlled room, and no remote login path other than Tailscale SSH. Additionally the file is `0600` and git-ignored, and the recipient address is deliberately *not* a secret — it is a constant in the script, where a change to it is visible in review rather than sitting in an untracked file.

**Reconsider when.** Any of: FileVault is enabled and this stops being a plaintext-on-an-unencrypted-disk question; a second person operates the platform, since a shared credential to one person's mailbox is a different proposition; or the alerting grows beyond the health daemon, at which point a dedicated account costs no more than the second consumer would. Rotating it is one revocation and one file, so this is cheap to reverse and should be reversed rather than argued about if the situation changes.

**Status.** In force since 2026-07-26. Verified by delivering all three mail kinds — baseline, failure and recovery — to the live mailbox.

### 15.8 The Public Landing Page Shows an Admin API Error to an Anonymous Reader

**Situation.** `/` became a public, session-aware page on 2026-08-27. It reads `useSession()`, and when the `/admin/me` call fails with anything other than a 401 it renders `ErrorState`, whose body is `describeError(error)` — the API's own message, unparaphrased. Before this the same component only ever rendered behind the shell, on routes an unauthenticated reader is redirected away from. It is now among the first things an anonymous visitor from the internet can see when the admin entrance is unwell.

**Why accepted.** The message is not new text written for this page; it is whatever the backend chose to return, and §5 of [backend.md](../backend.md) is where that choice is made and constrained. Error bodies there are already written for a possibly-unauthenticated audience, because `/login` is public and has always rendered these same states from this same component. What changed on 2026-08-27 is the route, not the disclosure. The alternative — a generic "something went wrong" on `/` alone — splits one failure across two vocabularies and makes the public page the one place a reader cannot tell an unreachable API from a refused call, which is the distinction the panel exists to draw.

**What carries the load.** The backend deciding disclosure at the point of the error, and the 401 path never reaching this branch: an ordinary unauthenticated visitor is `status === 'unauthenticated'`, which renders Sign in and no diagnosis at all. Only a non-401 failure — the admin API down, unreachable, or answering 5xx — reaches `ErrorState` here. `landing-page.test.tsx` pins which session state renders which action.

**Reconsider when.** A non-401 failure starts returning messages that name internal hosts, filesystem paths or dependency versions. That is worth fixing at the source rather than by hiding it at `/`, because `/login` would be showing the same string to the same reader.

**Status.** In force since 2026-08-27, recorded 2026-08-28 with the landing page's follow-up pass.
