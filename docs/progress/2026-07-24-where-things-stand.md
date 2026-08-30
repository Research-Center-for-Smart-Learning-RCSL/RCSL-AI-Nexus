# Where things stand

[← the progress log index](../PROGRESS.md)

> **A point-in-time snapshot, written 2026-07-24, kept for the record and not maintained.** The plan lives in [ROADMAP.md](../ROADMAP.md) and the control-by-control inventory in [security.md](../architecture/security.md) §13.0. Where this disagrees with either, or with a dated entry in the log, this is the one that is wrong.

Phase 1's functionality is complete. Inference, authentication on both admin
entrances, and the management API are all built and tested, and every screen
in the frontend now reaches a real backend. The remaining Phase 1 items are
operational rather than functional.

**The Mac Studio is deployed and serving.** The first `docker compose up` ran on
2026-07-26; `migrate` provisioned the two least-privilege roles and the live
database enforces them, GPU inference runs at 100% GPU, and a chat completion
goes end to end through key verification, quota, the proxy check, the country
filter, the routing policy and back out to a usage record. The tailnet
management entrance is reachable and every screen works against the real backend.
The backend suite runs here too: 359 tests on Python 3.12 against a real
Postgres 17 — **773 as of 2026-08-05** (680 unit, 93 integration skipped without
`TEST_DATABASE_URL`), beside 233 on the frontend.

What is still unverified, and by what — **this paragraph is a summary and has
drifted from the dated entries below more than once; where they disagree, they
win**:

- **nginx and the network path to the public entrance**, which wait on the NTNU
  proxy administrator. The entrance's *application* is no longer part of this:
  its full login flow — password, TOTP, session, logout — was driven end to end
  on 2026-08-02 (PROGRESS 2026-08-02). What is untested is everything between a
  browser on the internet and that socket. **Reopened in part on 2026-08-04 by
  the rename** to `llm.rcsl.online` and `llmapi.rcsl.online`: the clean
  `verify-public-entrance.sh` run of that morning attests to hostnames being
  retired.
- **MLX**, which has an adapter, no model registered against it, and no
  `mlx_lm.server` installed on the host. Since 2026-08-05 its tool path is
  **refused rather than silently reachable** (`MLX_TOOL_CALLING_VERIFIED`,
  default false), so the one way this could have failed invisibly now fails
  loudly instead. That closes the trap, not the verification.
- **A real agent client.** The loop itself is measured — ten rungs, all passing
  on `glm-4.7-flash`, including a multi-step debugging task — but that is a
  harness with tools it wrote itself. What no test covers is Codex or a
  comparable client, with prompts tuned for a model this deployment does not
  have, against a real repository. The harness answers "can the loop run"; it
  does not answer "is the work any good".
- The **external dead-man's switch**: a monitor on the host it watches cannot
  report that the host is off, so the heartbeat relies on a person noticing a
  mail that did not arrive.

**The unattended-recovery chain is no longer on that list.** Both of the
reconciler's repair paths were exercised by real boots with injected faults on
2026-07-26 — the binding half at 21:05:31, the container bring-up half at
21:52:14 — and the dated entries above record both.

*Corrected 2026-08-05.* Until today the paragraph here said the opposite:
"**Neither repair path has been exercised by an actual reboot** … the chain is
repaired-but-unproven". It was written before those two boots and never
updated, so this section contained a bullet and a paragraph asserting contrary
things about the same property, three lines apart. That is a sharper version of
the warning at the top of this section — a summary drifting from the dated
entries — because here it drifted from *itself*. The rule stands and is worth
restating: **where a summary and a dated entry disagree, the dated entry wins.**

What the two boots do and do not establish is worth keeping. They establish the
repair working at boot with everything else on the machine moving at once,
which is the part a hand test cannot reproduce. They do **not** establish that
either fault occurs unaided: the binding race is evidenced by the 16:45 boot,
and Docker failing to restore by the 19:10 boot alone, whose cause is still
unknown. Both faults are worth remembering in their own right — Docker Desktop
restoring containers before `tailscaled` has the tailnet address, so nine
containers run `healthy` and publish nothing while `restart: unless-stopped`
never fires; and the 19:09 boot where Docker restored nothing at all and
**nothing on the host was responsible for the stack being up**, because Docker
had always happened to do it.

### If you are picking this up cold

Read this section, then the 2026-07-26 entries above, then
[runbooks/first-deploy.md](../runbooks/first-deploy.md) §1.1. The single most
useful thing to know is that the day found **eight defects of one kind**: a
control designed, written down, marked done, and not actually in force — the
account-split test asserting nothing, the Ollama bind not surviving a reboot, the
pnpm allowlist inert, the tailnet ACL never applied, the frontend's admin URL
baked at build time, a registered model with no reachable download action,
Grafana's host port that had never once bound because it was declared on an
`internal` network, and the unattended-recovery chain itself, where
`restart: unless-stopped` was documented as what brings the platform back and does
not restore a dropped port binding. None looked wrong. Tests passed, images built
clean, health checks were green. They surfaced only when someone walked the whole
path for the first time. Assume the same class of thing remains in the parts that
have not been walked yet — the public entrance, MLX, and anything the runbook has
not made someone do end to end.

**Two of the eight were only found because a different investigation walked past
them**, which is worth knowing about the remaining surface: Grafana's port was
noticed while chasing the reboot fault, and the reboot fault itself was noticed
only because §1.1 says to `curl` the gateway rather than trust
`docker compose ps`. Nothing was monitoring either. There is no alerting on this
platform yet, so "it looks fine" currently means "nobody has asked it a question
it could fail."

**A related habit the day kept punishing: checking in a way that can only return
one answer.** Three times — the `tailscale status --json` probe for SSH host keys
that read a nonexistent field, `docker compose up -d` assumed to rebuild a port
forward when it is a no-op against a running container, and a first draft of the
reconciler that would have enumerated containers before Docker finished restoring
them. Each produced a confident wrong answer rather than an error. When a check
passes, it is worth asking what a failure would have looked like.

The machine has **no out-of-band management**. The dividing line for remote work
is whether an action can affect the next boot; the runbook states this after §1.1.

One thing still exists as an API with no dedicated UI: the download progress
endpoint, which the models table polls but no page surfaces on its own. The
routing policy editor now exists, so a policy is no longer curl-only.

**Phase 2 is complete but for two items, as of 2026-08-05.** Built: both
runtime adapters, node management, the multi-tenancy boundary, the logs and
usage screens, the observability emission stack, the knowledge base with
retrieval, the audit and authorization completeness sweeps (2026-08-02), the
`/api-docs` gaps, `prompt_tokens`, tool calling, the expiring debug switch on
both credentials, and prompt template management (2026-08-05).

What is left in Phase 2 is **encrypted backups with a rehearsed restore**, and
**Storybook stories for `components/composed`**. Two further items are recorded
there as `[~]` rather than open, because the half that needed hardware is the
half that is missing: `MetricsPort` ingestion wants a host free-memory figure
nothing in a container can produce, and the *logging boundaries* half of §9.2 —
full prompt/completion logging with its own shorter retention — remains
unimplemented even though the switch that would gate it now exists on both
credentials.

Phase 1 has one unchecked box left, and it is listed under Phase 3: **Playwright
over the sign-in and enrolment screens**. Every other Phase 1 item is done,
including `lib/generated`, which closed on 2026-08-05.

**Using the knowledge base needs one piece of configuration that nothing
enforces at startup**: a routing policy on the `embedding` capability, naming a
registered embedding model on an Ollama node. Without it, uploads still parse
and store but indexing fails with a named error, and retrieval quietly returns
nothing. That is deliberate — a chat should not fail because the knowledge base
is unconfigured — but it does mean an operator who skips this step sees a
knowledge base that looks like it is working and never answers anything.
