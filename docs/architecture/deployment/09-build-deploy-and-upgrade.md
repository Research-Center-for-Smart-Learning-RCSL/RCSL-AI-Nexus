# 9. Build, Deploy, and Upgrade

[← Deployment Topology](../deployment.md)

**Images are built on the Mac Studio.** The development machine is Windows on x86 and the target is arm64, so `docker compose build` runs on the target host. This avoids operating a registry and cross-platform builds for a single-node deployment. If a second node is added later, publishing arm64 images to GHCR becomes worthwhile.

**Migrations run as a one-shot service**, never from an application entrypoint, because five containers start from the same image — the gateway, the two admin entrances, `parser` and this job — and the three that open the database would otherwise race:

```yaml
migrate:
  image: rcsl-ai-nexus:latest
  command: ["sh", "-c", "alembic upgrade head && python -m app.infrastructure.db_roles && python -m app.infrastructure.provision"]
  networks: [admin-data]
  restart: "no"
```

Every backend service declares `depends_on: { migrate: { condition: service_completed_successfully } }`, `parser` included — it needs no schema, only the image tag to exist. The two frontends are the exception and depend on their own admin entrance instead, which reaches `migrate` transitively.

The middle step is the one this file omitted until 2026-08-18, and omitting it produces a deployment that starts and then cannot read anything: `db_roles` creates the gateway and admin accounts and their grants, connecting as the schema owner, which is the only place that account is used. It has to run after `alembic upgrade head`, because a grant needs the table to exist, and before any application starts, because those accounts are what the applications authenticate as (§6 of [security.md](../security.md)). The `provision` step after it writes the single configured compute node (there is no node-registration endpoint until the SSRF guard ships; see [security.md](../security.md) §7.2) and reconciles any model left in a transient state by a crash.

**Routine upgrade**

```bash
docker tag rcsl-ai-nexus:latest rcsl-ai-nexus:rollback-$(date +%Y%m%d)
docker tag rcsl-ai-nexus-frontend:latest rcsl-ai-nexus-frontend:rollback-$(date +%Y%m%d)

git pull
docker compose build
docker compose up -d          # migrate runs first, then services restart
docker compose ps             # confirm migrate exited 0 and services are healthy
```

**Check the built image before recreating anything.** Two questions, and the
second was added on 2026-08-20 because a deploy that answered the first
correctly still took the platform down for four minutes:

```bash
# 1. Does the image carry the code you think it does?
docker run --rm rcsl-ai-nexus:latest python -c "import app.infrastructure.main_gateway"

# 2. Can it construct Settings the way a service will -- against real secret
#    files, in production mode? `migrate` is the first thing to try this, and
#    it fails the whole deploy when it cannot.
docker run --rm -v "$PWD/secrets:/run/secrets:ro" \
  -e ENV=production -e AUTH_MODE=tailnet -e METRICS_ENABLED=true \
  rcsl-ai-nexus:latest python -c "
from app.infrastructure.config import Settings
s = Settings()
print('secrets_dir', Settings.model_config.get('secrets_dir'))
"
```

The second is not the same question as the first, and that is the whole point:
the 2026-08-20 image imported every module and still could not read a single
file under `/run/secrets`, because the settings class had been composed in a
way that dropped `secrets_dir`. Nothing in the unit suite or CI can ask this —
`/run/secrets` does not exist on either — so the image is the only place it can
be asked, and asking costs one container that exits immediately. The mount is
read-only and the container is discarded; nothing here writes.

**[Updated 2026-09-05] The credential helper problem below is resolved.** The migration from Docker Desktop to Colima on 2026-09-05 replaced `credsStore: desktop` with `osxkeychain`, eliminating `docker-credential-desktop` from the registry path entirely. The workaround is no longer needed and the throwaway `DOCKER_CONFIG` trick is retired. The history is preserved because the diagnostic method — test the credential helper directly, expect an answer in milliseconds — applies to any credential store.

**A build that times out resolving a base image is not necessarily a network fault, and on 2026-08-25 it was not one.** `docker compose build` failed at `load metadata for ghcr.io/astral-sh/uv:0.5.14` with `DeadlineExceeded` while the host reached `ghcr.io`, a container reached both `ghcr.io` and `registry-1.docker.io` (`401` to an unauthenticated `/v2/` is reachability, not a refusal), the daemon's own proxy at `http.docker.internal:3128` answered when driven by hand, and the VM's disk was 37.7 GB of 2.0 TB. The distinguishing symptom is an absence: `docker pull` hung without printing `Pulling from ...`, so nothing had been requested yet and no network layer could be responsible. The cause was `docker-credential-desktop`, which `credsStore: desktop` puts in front of every registry operation and which hung with no output; `docker desktop diagnose` hangs identically and for the same reason, so it cannot be used to investigate this. Confirm it directly, and expect an answer in milliseconds:

```bash
echo "https://index.docker.io/v1/" | docker-credential-desktop get
```

To build while it is broken, bypass the helper with a throwaway config rather than editing the real one. `DOCKER_CONFIG` also relocates the CLI plugin search path, so `docker compose` is "unknown command" until the plugins are linked in beside it:

```bash
D=$(mktemp -d); printf '{"auths":{}}' > "$D/config.json"
ln -sfn ~/.docker/cli-plugins "$D/cli-plugins"
DOCKER_CONFIG="$D" docker compose build
```

This is anonymous pulling, which is correct for the three public base images this repository builds on and would not be for a private registry. It is a workaround: the helper stays broken, a Docker Desktop restart does not clear it, and the fix is a re-login or reinstall.

After any `up -d` that recreates containers, also confirm the published ports are actually bound — see the startup-ordering note below for why `docker compose ps` does not show this.

**Upgrading the Ollama runtime is not part of any of the above, and it has a step no container upgrade has.** The runtime is a Homebrew formula behind a LaunchDaemon, not a container: `online.rcsl.ollama.plist` runs `/opt/homebrew/opt/ollama/bin/ollama serve`, where `opt/ollama` is the symlink Homebrew repoints on upgrade. So `brew upgrade ollama` changes what the *next* launch will run and nothing about the process currently running.

```bash
HOMEBREW_NO_AUTO_UPDATE=1 brew upgrade ollama
sudo launchctl kickstart -k system/online.rcsl.ollama    # the daemon runs as _rcslollama
```

**The window between those two commands is the part worth knowing about.** Homebrew's automatic cleanup removes the previous version's Cellar as part of the upgrade, and the running server loads its inference workers from a path inside it — `Cellar/<version>/libexec/lib/ollama/llama-server`. The already-running workers hold open inodes and keep serving, so `/api/ps` still answers and resident models still generate; a model that has to be *loaded* has nowhere to load from. The failure is therefore invisible to a health check that asks whether the runtime answers, and it lasts until the daemon is restarted. Do the two commands together.

**That same cleanup is why this is the one upgrade on this host with no local rollback.** §9's rollback is a git checkout and a rebuild; here the previous binary is deleted from the machine by the upgrade itself, so going back means recovering an old formula from `homebrew-core`'s history and building it. Measured 2026-09-02: after `0.32.4 → 0.33.2` the Cellar held `0.33.2` alone. Nothing warns about this, and `brew services` is not the manager here — `brew services list` reports `ollama` as `none`, because the daemon is this repository's plist rather than the formula's.

**A restart unloads every resident model and nothing brings them back.** The registry's `state` column still says `loaded`, which is what an operator asked for and remains true as an intent; `observed_state` follows the heartbeat within its 30-second interval and reports the truth on its own. What no component does is re-warm them. They have to be loaded by hand, largest first, at the `context_length` the `models` row carries — Ollama keys a runner by its options, so a model warmed at a different context is resident and wrong, and the first real request pays a reload to correct it:

```bash
# Registry context_length, which is what ManageModels sends. Ollama clamps each
# to the model's own maximum; that is why /api/ps reads smaller numbers back.
for spec in "gemma4:31b-it-q8_0 262144" "qwen2.5:7b 262144" "nomic-embed-text 8192"; do
  set -- $spec
  curl -s http://127.0.0.1:11434/api/generate \
    -d "{\"model\":\"$1\",\"keep_alive\":-1,\"options\":{\"num_ctx\":$2}}" >/dev/null
done
```

An embedding model answers that call `400 does not support generate` and needs `/api/embed` with an empty input instead, which `backend/.../ollama_adapter/lifecycle.py` and `scripts/model-eval/run.py` both do for the same reason.

**Check four things afterwards, and the second is a security control rather than a smoke test.** The version (`/api/version`); that the runtime answers on `127.0.0.1:11434` and **refuses on both the LAN address and the tailnet address**, which is [security.md](../security.md) §7.1's loopback bind and is carried by `OLLAMA_HOST` in the plist rather than by anything that survives on its own; that `ollama list` still shows the store, which is `OLLAMA_MODELS` and `HOME` in the plist both still pointing at `/Users/Shared/ollama`; and that the three models are resident at the right contexts. `check-platform-health.sh` covers the first two on its five-minute interval.

**Budget the memory, because a version bump moves it.** 0.33.2 sizes `gemma4:31b-it-q8_0` at **33.55 GiB** resident against 0.32.4's 31.58, at the same 262144 context and the same quantisation — 1.97 GiB, taken off the static budget's headroom for nothing the operator asked for, moving it from 13.95 to 11.99 GiB. The heartbeat writes the new figure into `observed_memory_gb` and `MemoryBudgetService` uses it immediately, so the guardrail is correct without intervention; what changes is how much room is left for a model that is not yet loaded. Re-read the headroom after any runtime upgrade before planning one.

**Deploy from a commit, not from a working tree.** The rollback path below is a git one, so an image built from uncommitted changes corresponds to nothing and can only be rolled back to whatever image tag happens to survive.

**Rollback.** Check out the previous tag and rebuild. Alembic downgrades are written only where a migration is genuinely reversible; otherwise recovery is a database restore, which is why §9.4 of [security.md](../security.md) insists restores are rehearsed.

The `rollback-YYYYMMDD` image tags above are the faster path when the rebuild itself is what has to be skipped, and the convention is that **they name the last build known to be good, not simply the previous one**. Re-tagging before every build would overwrite a good target with a bad one on exactly the deploy that is fixing something: on 2026-07-29 the second deploy of the day was replacing a build with a known wire-protocol defect, so `rollback-20260729` was deliberately left pointing at the build before *both*. A tag that means "whatever ran last" is worth nothing at the moment it is needed.

**Some changes cannot be deployed in either order.** A routing policy for a capability the running image does not know is refused by `ManageRoutingPolicies`, so the code that widens the capability set has to ship before the policy that uses it can be written. Expect a deploy followed by a configuration step rather than a single atomic change; the first-deploy runbook §7 carries the `assist` case.

**[Updated 2026-09-05] The port binding race described below no longer exists.** Under Colima (which replaced Docker Desktop on 2026-09-05) containers bind to `127.0.0.1` rather than the tailnet IP — the Docker daemon inside the VM has no host interfaces to bind to. `.env` sets `TAILNET_IP=127.0.0.1`, and a socat LaunchDaemon (`online.rcsl.socat-forwards`) waits for the tailnet address to appear on an interface and then forwards from `100.108.250.62:{8000,8002,3001}` to `127.0.0.1`. This eliminates the race structurally: Docker always binds loopback (which always exists), and socat starts only after `tailscaled` has the address up. The reconciler still covers the "Docker did not restore containers" failure, which is possible under any runtime. The analysis below is preserved as reference for the design of the reconciler and the socat forwarder.

**Startup ordering under Docker Desktop, and why `restart: unless-stopped` did not cover it.** `${TAILNET_IP}` had to exist before Docker bound to it, and at boot it did not: Docker Desktop restored containers roughly 21 seconds in on 2026-07-26, before `tailscaled` had put the address on `utun0`, and every forward naming it failed with `listen tcp4 100.x.y.z:8000: bind: can't assign requested address`.

**What decides that race is `tailscaled`'s own startup, and it varies by more than the whole margin.** Seven boots on 2026-07-26 bracket it. Docker is the *less* variable side — 10.3 to 14 seconds from `tailscaled` starting to its first `exposer.Add`, on every boot where it bound at all — but it is not a constant, and the two boots that set the low end of that range are the two most recent.

| boot | `tailscaled` start | address usable | Docker's `exposer.Add` | margin |
|---|---|---|---|---|
| 16:45, failed | 16:45:15 | 16:45:32 (+17s) | 16:45:29 | **−3s** |
| 17:21, passed | 17:21:48 | 17:21:48 (+0s) | 17:21:59 | **+11s** |
| 18:08, passed | 18:08:14 | 18:08:23 (+9s) | 18:08:25 | **+2s** |
| 19:09, failed for another reason | 19:09:59 | 19:10:00 (+1s) | *never* | *no race* |
| 19:43, passed | 19:43:28 | 19:43:37 (+9s) | 19:43:39.7 | **+2.7s** |
| 20:24, passed | 20:24:22 | 20:24:24 (+2s, cache hit) | 20:24:32.3 | **+8.3s** |
| 20:29, passed | 20:29:06 | 20:29:15 (+9s, cache miss) | 20:29:16.4 | **+1.4s** |
| **21:02, fault injected** | 21:04:13 (held 90s) | 21:04:14 (+1s, cache hit) | 21:02:56 (**bind failed**) | **−78s** |

**The last row is not a measurement of this race; it is manufactured weather and belongs to no distribution here.** `tailscaled` did not start on its own, so its column records the release rather than the boot. The only number in it that means anything is the margin: the natural ceiling is +1.3 seconds and the injector produced −78, sixty times over. That is what the ninety-second hold buys, and the three failed binds at 21:02:56 are the receipt.

**The budget is shrinking, and it is now small enough to state exactly.** Docker's lag across the six boots where it bound: 14.0, 11.0, 11.0, 11.7, **10.3**, **10.4** seconds — the two lowest are the last two, so the earlier "stable 11 to 14" reading was the small sample talking. Meanwhile every cache-miss boot has put the address up at exactly 9 seconds, three times with no spread at all. `10.3 − 9 = 1.3s` is the whole of what protects a cache-miss boot, and 20:29 passed by 1.4.

**The fourth row is what the table cannot measure.** It records a race with only one runner: the address was up in a second and Docker never bound anything, because it never restored a container. Winning this race is necessary for a boot to succeed and nowhere near sufficient, and the three-row version of this table quietly implied otherwise.

**The variable is whether the netmap disk cache loads.** With it, the address is up in the same second `tailscaled` starts, because it needs neither the network nor the control plane — at 17:21:52 the daemon was still reporting `You are logged out ... failed to resolve controlplane.tailscale.com` with the address already on `utun0`. Without it, the address waits for control: 9 seconds on the third boot, 17 on the failing one. The cache is written when a new netmap arrives from control, and a boot that *loads* it does not rewrite it, so caches do not chain: a boot that wins by eleven seconds leaves nothing behind and hands the next one the slow path. Applying a tailnet ACL also invalidates it, since the netmap carries the packet filter. The model has now made four predictions and all four held, with the alternation holding across seven boots and no exception: 18:08:23 wrote, so 19:09 loaded (+1s); 19:09 loaded without rewriting, so 19:43 missed (+9s) and wrote at 19:43:38; 19:43 wrote, so 20:24 loaded (+2s) and logged no write in its session; 20:24 loaded without rewriting, so 20:29 missed (+9s) and wrote at 20:29:15. Load-without-rewrite now rests on three observations rather than one. By the same rule the boot after 20:29 is a fast one.

**That last prediction was never tested, and the model took its first exception instead.** At 21:00:20 `tailscaled` was restarted by hand — a rehearsal of the recovery command §1.1a documents for a SIGKILLed injector — and at 21:00:27 it came up on `netmap cache is not available`, thirty-one minutes after the 20:29:15 write that should have been sitting there for it. A time-to-live does not explain it: 18:08:23 wrote and 19:10:00 loaded sixty-one minutes later. The one clean distinction is that this was a daemon restart inside a running session rather than a boot, and every hit the model has ever recorded followed a reboot. So there are now two live possibilities with one observation each — the model is wrong, or restart and boot are not the same event for this cache — and until they are separated the alternation may only be applied to boots. The prediction for the boot after 20:29 went untested because the injector held `tailscaled` down through it; the daemon that started at 21:04:13 loaded the cache written at 21:00:30 and logged no rewrite, which makes load-without-rewrite four observations and predicts a cache miss on the next boot.

**What the model does not buy is a losing boot on demand, and 20:24/20:29 settled that it never will.** Those two were a deliberate back-to-back reboot aimed at the second one, which is the cache-miss boot. The lever worked mechanically — no cache, address at 9 seconds, margin down from 8.3s to 1.4s — and still passed. With cache-miss boots pinned at 9 seconds (three observations, zero spread) and Docker's floor at 10.3, the lever's ceiling is a 1.3-second margin; it cannot go negative. Only 16:45 lost, on a 17-second address that has not recurred in six subsequent boots.

**The zero-spread half of that is now falsified, and the alternation half is now five for five.** The 21:51 boot — §1.1b's injection, which had no reason to be about this — was predicted to miss the cache and take 9 seconds. It missed the cache, which is the fifth consecutive confirmed prediction and the point at which load-without-rewrite stops being provisional. The address took **11 seconds** (`tailscaled` at 21:51:30, `peerapi` on 100.108.250.62 at 21:51:41), so cache-miss boots measure 9, 9, 9, 11, 17 rather than a constant, and 16:45's 17 seconds is better read as the top of that distribution than as an outlier retired by later boots. Recomputing, `10.3 − 11 = −0.7`. That subtraction takes the extremes of two distributions from different boots, which is exactly the reasoning this file has been careful to avoid elsewhere, and 21:51 produced no margin observation at all because the stack was deliberately stopped and Docker bound nothing. So the defensible correction is the weaker one: **the margin distribution is wider than three samples made it look, and "rebooting cannot lose" was overstated**. The conclusion it was supporting — inject rather than reboot — is unaffected and now rests on repeatability rather than on a guarantee: a 90-second hold is six times the margin Docker needs to lose by, and a 9-to-17-second address distribution is weather. The reconcile log's "15 seconds" for the same event is its five-second sampling granularity, not a measurement; the address timings above all come from `tailscaled`'s log. 21:51:41 also wrote the cache, so the next boot is predicted to load it.

**So the repair path is exercised by injecting the fault, not by waiting for it.** `launchd/delay-tailscaled-once.sh` holds `tailscaled` down for 90 seconds at boot — six times the margin Docker needs to lose by — so Docker binds before the address exists and the reconciler has to do what it was written for. It is a test tool, deliberately absent from the runbook's install list, and it deletes its own plist as its first action so it can only ever affect one boot. Procedure and the risk it carries (the host is off the tailnet for the duration, so a person must be at the machine) are in runbook §1.1a.

**It was run on 2026-07-26 at 21:02 and the repair path walked for the first time.** Docker bound at 21:02:56, seventy-eight seconds before the address existed, and failed on exactly the three services that name it — `:8000`, `:3001`, `:8002`. The reconciler found all three dropped, recreated them, and logged `OK: all bindings restored` at 21:05:31; nine services, six matching bindings and six entrances at 200 afterwards. What that establishes is the repair working *at boot*, with Docker Desktop restoring containers and the daemon settling and the address arriving all at once — the part a hand test cannot reproduce. It does not establish that the race occurs unaided, which 16:45 already did, and it says nothing about the container bring-up path, which this injector cannot reach because it holds back the address rather than the daemon's restore.

**That second path has an injector of its own, and it is much cheaper.** `launchd/stop-stack-once.sh` (runbook §1.1b) stops the stack and leaves the reboot to a person; `restart: unless-stopped` then does the work, because the "unless" means a container that was explicitly stopped is not restored when the daemon returns. The reconciler wakes to precisely the state the 19:09 boot left it — everything present, nothing running — and has to bring the platform up with everything else at boot moving at once. Unlike the address injector it needs nobody at the machine: the host stays on the tailnet for the whole window, so a failed test is recoverable from anywhere with `docker compose up -d`. It refuses to run unless the platform is currently whole and, most importantly, unless `nexus-reconcile.log` shows the reconciler ran on *this* boot — the presence of a plist is not evidence that launchd loaded it, and rebooting with the stack down and nothing scheduled to raise it is the one way this injection becomes an outage instead of a test. What it reproduces is the state, not the cause: why Docker Desktop restored nothing that once is still unproven.

**It was run on 2026-07-26 at 21:51 and the second path walked, 51 seconds into the boot.** The stack was stopped at 21:50:38, the machine rebooted, and the reconciler started 7 seconds into the boot, had the address at 21:51:45, found all nine services missing at 21:52:01, and reported `stack up: all expected services running` followed by `all published bindings intact` at 21:52:14. Docker Desktop restored *none* of the nine, which is the first observation of the `unless` in `restart: unless-stopped` surviving a reboot on this machine rather than merely being promised by the compose file. The last line was `intact` and not `OK: all bindings restored`, as predicted before the run: the reconciler waits for the address first, so by the time `up -d` ran the forwards were built correctly on the first attempt, and no `can't assign requested address` appears in the backend log for this boot. Two injectors, two paths, neither substitutable for the other — now evidenced rather than argued. What it does not establish is Docker's restore failing unaided, which remains the 19:10 boot alone.

**The cost of the repair at boot is roughly double the hand-tested cost, which is itself the finding.** The named-set precondition took 27 seconds against a stable 16 on four healthy boots, and the binding scan took 40 seconds — twelve seconds between each of the three detections — where on a healthy boot the same scan completes inside one second. `broken_services()` contains no sleep, so that is entirely `docker inspect` latency while the machine is still busy. Of the 77 seconds from address to restored, more than half was spent looking rather than repairing.

**The 21:51 injection narrows what that cost is actually attributable to.** The same settle loop took 15 seconds there — its structural floor, four samples with three five-second sleeps, the fastest it can complete and still be the loop — and the binding scan did not appear at all. The difference is not boot versus hand test: it is whether there is a *running* stack to inspect. Against nine stopped containers the `docker compose ps` calls cost nothing measurable; against nine running ones on a busy boot they cost 11 seconds over the healthy baseline and the `docker inspect` sweep costs 40. Of the reconciler's 44 seconds at 21:51, 31 were waiting (15 address, 1 daemon, 15 settle) and 13 were `up -d` taking nine services from nothing to all-running, postgres health gate and `migrate` included. That 13 seconds is the figure no hand test had produced: the one hand run of this path took 16 seconds for a single already-imaged service, essentially all of it the settle loop.

**The cause recorded here until 2026-07-26 was wrong**, and it is worth keeping the correction rather than quietly replacing it. It named a logtail bootstrap-DNS retry loop. The third boot ran that loop in full — twelve DERP hosts, then a second round for `controlplane.tailscale.com` — and still passed with two seconds to spare; every attempt in it fails inside one second with `network is unreachable` rather than timing out, and all four boots in the log ran it. It was correlation, read as cause from two data points. The evidence and the correction are in [PROGRESS.md](../../PROGRESS.md) 2026-07-26.

The ordering therefore cannot be relied on in either direction, and the reconciler below is the only thing that covers a lost race.

This paragraph previously said to rely on `restart: unless-stopped` to recover once the interface appears, and told the reader to confirm rather than assume. The confirmation disproved it. **A failed bind does not stop the container.** Docker Desktop logs one warning, does not retry, and the container starts normally; with nothing exited, the restart policy has no event to act on. The result is nine containers `Up`, the gateway reporting `healthy`, and four of six published ports simply absent — a state in which `docker compose ps` looks entirely correct.

The recovery is `launchd/reconcile-port-bindings.sh`, installed as a LaunchDaemon (runbook §7). It waits for the address to be on an interface, the daemon to answer, and the set of running services to stop changing; it then brings up whatever is not running (the second failure, below) and recreates only the containers whose requested `PortBindings` have an empty `NetworkSettings.Ports`.

**A second failure at boot needs the same daemon, and it is not a variant of the first.** On the 2026-07-26 19:10 boot — the macOS 26.5.2 update reboot, recorded in `InstallHistory.plist` at 19:09:47 — Docker Desktop restored *nothing*: all nine containers had stopped cleanly at the 19:04 shutdown, the engine was running again at 19:10:37, and no `exposer.Add` was ever logged — against a full nine on the 18:08 boot. Whether the update reboot is what made the difference is unproven and nothing here depends on it; the two boots that restored were plain reboots, which is one correlation. The containers, their configuration and their restart policy were all intact; they were simply never started. `restart: unless-stopped` is a promise the Docker daemon makes, kept on the two boots before that one and broken on this one, and **nothing else on this host ever ran `docker compose up`** — the reconciler's own repair path fires only for containers that are already running with a dropped forward. There was no second line of defence, and the platform stayed down until a person looked.

**The reconciler reported success while standing in it.** Its third precondition waited for the container count to stop changing but required the count to exceed zero before it would settle, so an empty platform spun to the ten-minute deadline, and the binding sweep then found nothing wrong because a sweep over running containers finds nothing wrong when there are none: `all published bindings intact; nothing to do`, exit 0. That is the third instance of this document's recurring defect — a check whose timing or scope lets it produce only one answer — and it was in the code written to fix the second one.

**So the precondition now waits for a named set, not a count.** A count cannot distinguish "not restored yet" from "not coming back"; a list of expected services can, because a service that is absent is still in the list. Whatever is missing is brought up with `docker compose up -d`, the result is read back rather than assumed, and a platform that is still incomplete exits non-zero even when every binding that does exist is correct. The list is named in both this script and `check-platform-health.sh`, for the same reason each of them needs it. Keeping the two in step by hand did not work: `parser` and `qdrant` were absent from the health sweep's copy from the day each service was added until 2026-08-04 — six days for `parser` (added 07-29), five for `qdrant` (07-30) — so either could have stopped without it noticing. This paragraph said "four months" until 2026-08-18, which is longer than the repository has existed (first commit 2026-07-24); a figure nobody could have measured, in the sentence about a list nobody was checking, is the enumeration error this document keeps recording arriving twice over. The reconciler's copy was missing the same two, and that is the worse half: its list drives both the settle precondition and the `docker compose up -d` repair, so on a boot where Docker restored nothing — the 19:10 path this section is about — `parser` and `qdrant` would have been left down while it logged `all expected services running` and exited 0. The component whose job is the repair was blind to two of the services it was repairing. Since 2026-08-04 both scripts derive the list from `docker compose config --services` minus `migrate`, each keeping a literal only as the fallback for when that derivation fails, and the reconciler logs which list it ended up with.

**The read-back gets its own 120 seconds rather than what is left of the run's.** The deadline is absolute and one of the two ways into the repair branch is the settle loop timing out — the 19:10 boot's exact path — which leaves nothing. With nothing left, the first sample, taken in the gap between `up -d` returning and Compose reporting the container as running, prints `FATAL: still not running` about a stack that is starting. Reproduced with one injected lagging sample: without the fix, the FATAL is logged in the same second as `Container ... Started`; with it, one retry and `stack up: all expected services running`. A repair whose failure report is a race is not one anyone can act on.

**[Updated 2026-09-05] Under Colima, `colima stop && colima start` has the same container-loss behaviour described below — `restart: unless-stopped` still means an explicit stop is not retried. The reconciler now covers this at boot because Colima runs as a LaunchDaemon (`online.rcsl.colima`), and `check-platform-health.sh` still covers a mid-session restart on its five-minute interval.**

**Restarting Docker Desktop reached the same state and no reconciler covered it.** On 2026-08-25 `docker desktop restart` stopped all twelve containers cleanly — eleven `Exited (0)`, `qdrant` `Exited (143)` — and restored none, leaving the platform entirely down until `docker compose up -d` was run by hand. `restart: unless-stopped` was not at fault and was not a second chance here: a restart stops containers *explicitly*, which is exactly the "unless", so the daemon had no event to act on when it returned. The state was the 19:10 boot's, but the trigger was not a boot, and everything written for that state was boot-shaped — the reconciler was a LaunchDaemon that ran at startup, and both injectors that rehearsed it worked by rebooting. An operator restarting Docker Desktop mid-session therefore got no reconciler at all. What did cover it was `check-platform-health.sh` on its five-minute interval, which bounds the outage at five minutes plus however long the mail takes to be read; that is the only net under this case, which the port-binding reconciler's name rather obscures.

**It must recreate, not restart.** The forward is established when a container is *created*: `docker compose up -d` is a no-op against a container already running with a matching config, and `docker compose restart` reuses the container and leaves the backend's forwarding table untouched. Both were tried on the target host and neither restored a single binding; only `--force-recreate` did.

**That applies to the running container with a dead forward, and not to the stopped one**, which is why the script uses each in its own branch. A stopped service is started by a plain `up -d` and its forward is established at that moment: `grafana` stopped by hand and brought back this way had `127.0.0.1:3002` requested-equals-actual immediately afterwards, with `/login` returning 200. The distinction matters because using `--force-recreate` for both would rebuild containers a start would have fixed, and using `up -d` for both would silently do nothing in the case the script was originally written for.

**Checking for this state.** `docker compose ps` cannot see it. Compare requested against actual — an empty list on the actual side is the signature, while `null` means the service never published anything:

```bash
for c in $(docker compose ps -q); do
  printf '%-38s %s\n' "$(docker inspect $c --format '{{.Name}}')" \
    "$(docker inspect $c --format '{{json .NetworkSettings.Ports}}')"
done
```

**And something has to run that check when nobody is looking.** The reconciler covers the boot; a reconcile that fails, or a daemon that never runs, leaves precisely the state above with nothing to announce it — the original fault was found only because a person read four logs by hand. `launchd/check-platform-health.sh` (runbook §7) runs every five minutes and mails on a change of state: the expected service list, requested-versus-actual bindings, the six entrances over their published ports, and Ollama answering on loopback but not on the tailnet address. Three properties are deliberate. It compares services against a fixed expected list rather than enumerating what is running, because a container that is entirely gone would otherwise not appear in the enumeration and the sweep would report success. It asks that question as `docker compose ps --services --status running`, because plain `ps` excludes only *stopped* containers and would count a paused or restarting one as running — Docker Desktop's Resource Saver paused containers (no longer applicable under Colima, which has no equivalent), and `postgres`, `redis` and `prometheus` have no entrance probe, so this check is the whole of their coverage. And it sends a heartbeat daily even when nothing is wrong: a monitor on the host it watches can report "up but not serving" and can never report "powered off", so the only way silence becomes evidence is for something to be expected to break it.

**Its own liveness is the state file's mtime, and that had a hole exactly where it was read.** The log is events-only, so "did this ever run" is answered by `/opt/homebrew/var/nexus-health.state`, which every run rewrites — and the runbook's acceptance criterion is that the mtime is under five minutes old. With the plist at `RunAtLoad=false` and a 300-second interval, no run happened in the first five minutes of a boot, so the freshest mtime available in that window predated the boot: three to eight minutes old depending only on where the reboot fell in the previous interval, against a five-minute criterion. The 20:24 and 20:29 reboots were 4m37s apart and no run happened across either of them; the 20:26 check passed with thirteen seconds to spare, by luck. `RunAtLoad` is now true and the boot-time run is suppressed by the boot grace, which rewrites the state file verbatim and exits — it claims nothing, because nothing was checked, and updates the one thing it is entitled to claim.

**The boot grace it relies on to do that had never fired.** It parsed `sysctl -n kern.boottime`, whose output is `{ sec = 1785068938, usec = 428375 } ...`, with `s/.*sec = \([0-9]*\).*/\1/`; the leading `.*` is greedy and matched through to `usec`, so the boot time was the microseconds field, uptime was the Unix epoch, and the comparison could only ever answer "not in grace". That is the fourth instance of this document's recurring defect, and this time it was in the check whose only job was to have two answers — it also put a nine-digit `uptime` line in every alert mail sent before the fix. The pattern is now anchored at the start of the line, and the grace is 240 seconds rather than 300 so that it sits clearly below the interval instead of on the boundary, where whether the first scheduled run of a boot evaluates or is skipped came down to how long launchd took to load the job.

**The 21:02 boot confirmed the whole arrangement, and the confirmation did not come from the state file.** That file's mtime cannot distinguish the two designs: `StartInterval` counts from load either way, so the first scheduled write lands at load+300 whether `RunAtLoad` fired or not, and it overwrites the boot-time write five minutes later. The unified log separates them — four spawn/exit pairs, at 21:02:43.356→.473, 21:07:43.678→44.286, 21:12:44.309→.838 and 21:17:44.858→45.386. The first ran at an uptime of seven seconds and finished in **117 milliseconds**; the three full-path runs cluster at 528–608ms, because that path makes six curl probes, a `docker info`, a `docker compose ps` and ten `docker inspect` calls. Nothing but the grace path exits 0 in a tenth of a second while writing no log line, and none of the four sent mail. `launchctl print`'s `runs` counter is the wrong instrument here: it carries no timestamp, so `runs = 3` cannot be told apart from `RunAtLoad` plus two intervals without separately recovering when it was read.

**And the boundary the 240 was chosen to avoid turned out to be seven seconds away.** The first scheduled run of that boot fired at an uptime of 307 seconds. Had the grace stayed at 300 it would have evaluated by a seven-second margin; eight seconds more launchd latency and the same healthy boot would have skipped it and pushed the first real check to ten minutes. The coin flip described above was not hypothetical, and 240 turns that seven-second margin into sixty-seven.

**The grace also did its actual job for the first time on that boot.** From 21:02:56 to 21:05:31 the platform was genuinely broken — three bindings dropped, three tailnet entrances down — and no mail went out, because every moment of it fell inside the window the reconciler owns. Before 20:45 the grace could not fire at all, and after the fix there had been no failing boot to exercise it. Had the repair not worked, the 21:07:43 run would have caught it and mailed, which puts the worst-case detection delay at ten minutes.
