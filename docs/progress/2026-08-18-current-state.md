# Current state

[← the progress log index](../PROGRESS.md)

> **A point-in-time snapshot, written 2026-08-18, kept for the record and not maintained.** The plan lives in [ROADMAP.md](../ROADMAP.md) and the control-by-control inventory in [security.md](../architecture/security.md) §13.0. Where this disagrees with either, or with a dated entry in the log, this is the one that is wrong.

**A summary, and therefore the least trustworthy thing here.** Two summaries in
this file have already contradicted the dated entries below them, one of them
contradicting a bullet three lines above itself. The rule that follows from
that: **if this block's date is older than the newest entry below, distrust it
and read the entry.** It is here because the file is ten thousand lines long
and nothing else answers "what is the state of this, right now".

**This block was dated 2026-08-08 for ten days, and the 2026-08-18
documentation audit found ten false sentences in it** — the model in service,
the routing policy, the memory figures, three counts, the agent loop's score,
and an item still listed as unverified that had been verified on 2026-08-09.
That is the rule above earning its keep rather than an argument against it, and
it is why this paragraph now says what a re-date does and does not buy.

**Re-checked in this pass**, against the live database and the suites rather
than against another document: the four routing policies and the six registry
rows (`psql` against the running Postgres), resident memory and the headroom
derived from it, every count in the table below, the number of Playwright paths,
and the model each capability resolves to. **Not re-checked, and still resting
on the dated entry that produced it**: the agent-loop rungs (2026-08-16), the
public entrance's nine checks (2026-08-08), the SSD and oversubscription
measurements (2026-08-14), the "all green" on the gates row, and everything
under "Not verified".

**Running.** Eleven containers on the Mac Studio: three ASGI apps (gateway, two
admin entrances), two frontends, Postgres, Redis, Qdrant, the isolated parser,
Prometheus and Grafana, with `migrate` exiting 0 ahead of them. Ollama runs
natively and holds `qwen3.6:35b-a3b-q8_0`, `qwen2.5:7b` and `nomic-embed-text` —
**43.63 GB resident against a 51.2 GB budget**, summed from
`models.observed_memory_gb` on 2026-08-18 (37.97 + 5.32 + 0.34). **This said
45.3 GB from 2026-08-16 until 2026-08-18**: the runtime's observed figure for
`qwen36-35b-a3b-q8` has settled at 37.97 GB against the 40.0 GB measured on the
day it was registered, and nothing had gone back to re-read the column. Four
routing policies, read from `routing_policies` the same day: `chat` and `code`
both on `qwen36-35b-a3b-q8`, `assist` on `qwen7b`, `embedding` on `embedder`.
**Deliberation is off for `code` alone.** `code.thinking` is `false`;
`chat.thinking` is `NULL`, and a `NULL` takes the deployment default, which is
`OLLAMA_THINKING=true` — so `chat` deliberates unless the client sends `think`
itself. **And `chat` is the only policy carrying a fallback**: `qwen7b` at
priority 100 behind `qwen36-35b-a3b-q8` at 200, which is right for a person and
wrong for an agent, and is why `code` has none. This block said "`chat` and
`code` (deliberation off)" until 2026-08-18, which reads as both, and named no
fallback at all. Three former main models stay registered at
`downloaded` and make the switch reversible in either direction:
`gemma4:31b-it-q8_0`, which held the role from 2026-08-07 until 2026-08-16,
`glm-4.7-flash:q8_0` before it, and `gemma4:31b-it-qat`, the q4 this ran on for
part of a day.

**Every row of the table below was measured on 2026-08-18 while this paragraph
was written**, not copied: `pytest --collect-only` for the two backend figures,
`vitest run` for the frontend one, and `ls` for the module, router, folder and
migration counts. The two count rows had already been corrected once earlier
that day, and on 2026-08-16 before that, and they had still drifted since: the
first correction found 742 unit tests recorded against 907 and twelve migrations
against fifteen, a third out, and named `gemma4-31b-q8` and a 36.3 GiB figure
that the entry at the top of this file had made untrue the same morning. **The
frontend row then drifted again inside ten days**, 296 against 308. The rule
above still applies to every sentence here that is not one of these numbers.

**Built.** Phase 1 is complete, including the **six** Playwright paths — the
five described below, and the full-stack one that landed 2026-08-10 and joins
the browser to a real gateway and a real Postgres. This said five until
2026-08-18.
Phase 2 is complete but for **the rehearsal half of encrypted backups** and
**Storybook**. The backup *mechanism* shipped 2026-08-18 and nothing has been
restored from it yet, which is deliberately reported as two claims rather than
one: security.md §9.4's own sentence is that an unverified backup is not a
backup, and this file has already recorded eight controls that were designed,
written down, marked done and not actually in force. The *logging boundaries* half of §9.2 closed on 2026-08-08 — full
prompt and completion logging, gated by the expiring switch that had been sitting
there unused, kept for days rather than months, and audited when read. It was the
last row in security.md §13.0 that said "not implemented".

| | |
|---|---|
| Backend | 32 use cases, 27 routers, 19 entity modules, 16 migrations (head `a4c1e07f2b9d`), **954 unit tests** (952 before 2026-08-20, 945 earlier on 2026-08-18), 120 integration tests that skip without `TEST_DATABASE_URL`. The first three counts are unchanged by the 2026-08-20 split, which is the check that the façades kept the top-level surface rather than a claim that nothing moved |
| Frontend | 21 feature folders, 20 screens, **376 tests across 46 files** (296, then 308, 345, 359 and 366, earlier on 2026-08-18; 374 across 45 until 2026-08-21, when the regression test for the assistant drawer's scroll added two). The count was 366 here until 2026-08-20 and the tree held 374 on the day it was written: the eight are a stale figure being corrected, not tests the split added, which moved 374 from 40 files into 45 without changing one of their names. Types generated from the backend's OpenAPI document and checked against every hand-written schema at compile time |
| Gates | ruff, ruff-format, strict mypy, pytest; tsc, eslint, vitest, a real `next build`, **six Playwright paths** (five until 2026-08-18, three days after the sixth landed); Trivy, pip-audit and pnpm audit advisory-only. **Not all green, and this row said so until 2026-08-18**; as of 2026-08-20 the last fifteen runs carry no failed conclusion, which is weaker than it reads — the `routing-selection.spec.ts` intermittent failed once that day and the run is green because it was re-run, so a green window here counts re-runs and is not evidence the flake is gone. On 2026-08-18: five of the last fifteen CI runs failed, every one of them on Playwright — three on `e2e-full-stack / Browser to gateway` and two on `frontend / Playwright`. `backend`, `frontend` and `audit` have not failed once in that window. The row was also false from 2026-08-07 to 2026-08-08 for a different reason, see below |

**Verified on real hardware**, not only in tests: the full inference path with
tool calling; the agent loop over ten graduated rungs including a multi-step
debugging task — **ten of ten only on `gemma4-31b-q8`, which serves nothing
now** (2026-08-07), and **nine of ten on the model `code` actually points at**,
where rung 8, error recovery, fails five runs out of five (2026-08-16); the
knowledge base end to end; both admin entrances' login flows; the
least-privilege database split; the unattended-recovery chain through two boots
with injected faults; and the GeoLite2 refresh. This said "ten graduated rungs"
with neither qualifier until 2026-08-18, two days after the model underneath it
changed.

**One open question, raised 2026-08-05 and still deliberately not acted on.**
Free memory on this node swings between roughly 12 GB and 37 GB of 64 depending
on whether it is serving — the weights are wired during inference and revert to
evictable file-backed pages when idle. **The tail between the two is 19
minutes, measured twice on 2026-08-07**, the trigger is a single request of any
size, and the machine spends those nineteen minutes under a gigabyte free with
swap at 0 bytes and nothing degrading. The leading candidate is still to do
nothing, now with more behind it. What actually limits the deployment is the
static budget's headroom — **7.57 GiB on 2026-08-18**, 51.2 GiB less the 43.63
the runtime reports resident — which none of this touches. **This said 9.87 GiB
from 2026-08-05 until 2026-08-18**, a subtraction taken against 41.33 GiB of a
different model set; the headroom moves whenever the registry does, and the
registry has moved twice since without this line following. See the 2026-08-07
and 2026-08-05 entries and "Open decisions". **2026-08-13 priced the trade this
question was opened to consider and found the more interesting question is next
to it**: the main model *was* dense, so it read all of itself for every token,
and the gain available from a sparse model of the same or larger size did not
need the SSD at all. **That was acted on, and this sentence stood in the present
tense for two days after it stopped being true**: what serves `chat` and `code`
since 2026-08-16 is `qwen3.6:35b-a3b-q8_0`, 35B total on 3B active — a sparse
MoE, not a dense model.

**The SSD half is closed as of 2026-08-14, by measurement, and the answer is
no.** Through the mmap page faults Ollama uses the disk delivers 0.89 GB/s, not
the 7 GB/s the pricing assumed — and at a measured 1.29x oversubscription prompt
evaluation collapses 150x, ten times past the per-read timeout. What replaces it
is better and needs no disk: `qwen3.6:35b-a3b-q8_0` fits in 37 GB and measures
5.1x the generation and 7.7x the prompt evaluation of the model deployed then.
It was **not** measurably smarter on the evidence of that day — twelve checked
tasks put three candidates within noise of each other — so the case for
switching rested on the wall clock. **The eighteen-task set of 2026-08-15 then
did separate them, and not in the new model's favour**: 94.4% for
`gemma4:31b-it-q8_0`, 89.8% for `qwen3.6:35b-a3b-q8_0` and 87.5% for
`qwen3.6:27b-q8_0`, a 6.9-point spread across the three and 4.6 points between
the incumbent and its replacement, with the order holding every round. So the
case still rests on the wall clock — a round in 45% of the time — and it is not
a claim of a smarter model. **`code` and `chat` were both switched on
2026-08-16.** This block said "Nothing has been switched" for the two days
after, which is the most misleading sentence the 2026-08-18 audit found in it.
See the 2026-08-14, 2026-08-15 and 2026-08-16 entries.

**The public entrance was verified on 2026-08-08**, under the renamed hosts:
`verify-public-entrance.sh` passed 9 of 9 and has not been re-run since. **This
said "as of today" and kept saying it for the ten days the block's date stopped
being today**, which is the failure mode the rule at the top of this block
describes, written into the block itself. What remains there is three items
the script does not cover — explicit A records (the names are still
wildcard-synthesised), a `client_max_body_size` on the *inference* host, and
the administrator's confirmation that nothing logs request bodies.

**Not verified, and the list worth reading before trusting anything else.**
MLX, which has an adapter, no model registered against it and no server
installed — its tool path is now *refused* rather than silently reachable,
which closes the trap without doing the verification. An external dead-man's
switch, since a monitor on the host it watches cannot report that the host is
off.

**"A real agent client against a real repository" left this list on 2026-08-09
and was still sitting on it nine days later.** An operator's own Codex session
drove the real public entrance that day and found three defects the verification
harness could not, which is the strongest possible evidence that the client was
real. Two Codex installations have run against this platform since — the
operator's for days, and a teacher's through 2026-08-17 and 2026-08-18 — and
both are unbound at the client end as of today, with their keys deliberately
left live. What none of those sessions answers is the second half of the item,
which stays open and is stated under "What is still unverified": the harness
says the loop can run, and nothing yet says the work is any good.

**The body ceiling came off this list on 2026-08-08.** It had said the running
images predated it, so the gateway was still the one the 200 MiB probe measured.
The 2026-08-08 deploy rebuilt every application image, which put it in force as a
side effect — and it was then measured rather than assumed: a 5 MiB body with no
credential returns `413 request_too_large` with **zero bytes uploaded**, so the
refusal lands before the body is sent, which is what "refused before anything asks
who sent it" means. The envelope carries no `detail`, correctly: no credential
was resolved, so no debug window could apply to it.

The fuller version of that list, with what each would take, is under "What is
still unverified" further down.

### Two gaps that were recorded rather than fixed, closed

Both came out of the investigation above and neither was its cause. They are
here because "found and written down" is one step short of the thing that
matters, and this file has already recorded eight controls that got exactly
that far.

**The admin API never said its responses must not be stored, and neither did
the gateway.** Two responses in the whole codebase set `Cache-Control` — an SSE
stream at `no-cache`, an enrolment QR at `no-store, private` — and each because
somebody was thinking about that one response. Everything else said nothing: an
API returning users, keys, audit rows, transcripts and refusals, and a gateway
whose responses carry a caller's prompt and a model's completion. A cache told
nothing is not forbidden from storing, and the deployment has a cache-capable
intermediary in the path that this project does not administer — the openresty
host of §15.1. **"It is probably not configured to cache" is the same argument
as "nginx probably limits the body size"**, and `body_limit.py` records that one
being wrong on this deployment by 200 MiB.

`middleware/cache_control.py` now adds `no-store` on all three applications. It
is a pure ASGI middleware for the reason `metrics.py` and `request_context.py`
both give, and it is placed inside `RequestContextMiddleware` and outside the
perimeter middlewares, so a response that CSRF or the geo filter builds carries
it too — the responses with the most to say about a caller are the ones no
handler writes.

**Two things it deliberately does not do, and the tests are about those rather
than about the header.** It never overwrites a value a response chose: `no-cache`
and `no-store` are not interchangeable in how an intermediary treats a stream,
so widening the SSE header is a decision with its own risk rather than an
improvement, and it was left alone. And it matches an existing header
case-insensitively, because emitting a second `Cache-Control` line would leave
the intermediary to pick, which is the one outcome worse than saying nothing.

**One response still does not get it**, and the boundary is named rather than
left to be discovered: an exception escaping to Starlette's
`ServerErrorMiddleware` is answered outside every user middleware. That is
narrow — all three applications install their own handlers, so an anticipated
500 is built inside the stack — but it is not nothing, and a test that had
asserted otherwise would have been asserting the wrong thing. The first draft of
the rejection test did exactly that: it aimed at the public entrance's geo
filter, which reads `app.state` that only the lifespan populates, so it was
measuring a 500 from an unstarted application rather than a perimeter refusal.
It aims at the tailnet entrance's CSRF check now, which needs no state.

**Deployed and verified on the machine the same evening.** The image was rebuilt
and gateway, both admin entrances and the parser recreated onto it — the four
services that share `rcsl-ai-nexus:latest`; the frontend image was untouched
because no frontend source changed. Before the recreate the new image was
checked for the code rather than assumed to carry it, by importing the
middleware inside it.

What the live platform now answers: `cache-control: no-store` on `/healthz` from
all three entrances, **and on a 401 from both the admin API and the gateway** —
the perimeter-built response the middleware's placement exists for. `/readyz`
reports `ready: true` with `database`, `cache` and `runtime` all true on the two
applications that name their checks, the frontend answers 200 through its proxy
to the entrance that had just been replaced, Ollama still holds all three models
(it runs natively and no container touched it), and
`check-platform-health.sh --dry-run` reports `state OK` with no warnings across
all fifteen checks.

**One property is covered by test rather than by the deployment**: that a stream
keeps its own `no-cache`. Verifying it on the machine needs a real streaming
completion, which needs somebody's API key, so it was not done.

*A note on the verification itself.* The first health sweep here reported `000`
from all three entrances and looked exactly like the port-binding fault of
2026-07-26. It was the checking script: zsh does not word-split an unquoted
variable, so `set -- $u` left the URL unparsed and curl was handed nothing. The
platform was answering 200 throughout. Worth recording because the failure it
imitated is one this repository has actually had, and for ten seconds the
evidence for "the deploy broke the bindings" and for "the loop is wrong" was
identical.

**And four of the seventeen `secrets/*.example` files carried a trailing
newline**, against the rule `secrets/README.md` states in its own second
paragraph: the content of these files *is* the secret, so a newline is part of
it. `grafana_admin_password`, `metrics_scrape_token`, `qdrant_api_key` and
`qdrant_read_only_api_key` demonstrated the opposite of what the file next to
them documents. Stripped. This is only safe to leave stripped because the
`end-of-file-fixer` exclusion added with pre-commit earlier the same day stops a
tool from putting them back — the fix and the thing that holds it were found in
the wrong order, and both are needed.

### An intermittent CI failure, a diagnosis that measurement refuted, and the instrument that should settle it next time

`main` went red on the merge of #11 and the failing job was `e2e-full-stack`.
One assertion: `routing-selection.spec.ts` waiting for the routing-policies
table to show `beta (p100)` after the browser saved it. Checking the history
first, before touching anything, is what made the rest of this worth doing —
**the same assertion, the same locator and the same 5000 ms timeout had failed
three times that day on commits that touched nothing near it**, and five of the
last fifteen CI runs were red, every one on Playwright. So it was not the merge,
and the gates row in this file's summary block was wrong to say "All green".

**The re-run passed and `main` is green, which is the trap rather than the
result.** `playwright.config.ts` already argues the point in its own comment —
retries exist to tell a flaky test from a broken one, not to hide it — and here
the answer turned out to be neither of the two the comment anticipated.

**What the browser's trace establishes, and it is not a flake.** The failed run's
artifact carries the network log:

    30.572  PUT  /admin/routing-policies/chat   82.6 ms  -> 200, body says beta
    30.657  GET  /admin/routing-policies        15.2 ms  -> body says alpha

The GET was issued two milliseconds after the PUT's response arrived and came
back with the state from before it. Three things it is *not*, each checked
rather than assumed: not a browser cache hit — `serverIPAddress` is 127.0.0.1,
fourteen milliseconds of server think time, a `Date` of `14:26:30` against the
first GET's `14:26:28`, and no `Age`; not the Next proxy — `/admin/*` is a
`NextResponse.rewrite`, which does not cache; not a backend cache — nothing
caches routing policies, and `grep` over `adapters/cache` says so.

**Then I got it wrong, in the way this file exists to record.** The hypothesis
was that `get_session` (`di.py:259`) is a FastAPI `yield` dependency and
`session_scope` commits *after* the yield, so on FastAPI 0.139 the commit lands
after the response is sent and a fast follow-up read sees the pre-commit state.
A twenty-line reproduction on the same FastAPI version showed exactly that: the
client had the response 1.3 ms in, the read was served at 2.5 ms, and the commit
had not happened.

**Measuring the real application refuted it.** Instrumenting SQLAlchemy's own
`AsyncSession.commit` in-process — the app imported unmodified, an isolated
Postgres, the real admin entrance over a real socket — the commit finishes
**about two milliseconds before the client receives the response**, every round:

    round 1   commit +29.98 ms   client had the response +32.04 ms
    round 2   commit +35.28 ms   client had the response +37.34 ms
    round 3   commit +33.09 ms   client had the response +34.41 ms

The toy was missing what the real app has: five `BaseHTTPMiddleware` layers
(CSRF, identity, metrics, geo, body limit). `BaseHTTPMiddleware` buffers the
response, so the dependency exit stack — the commit — completes before the
outermost middleware hands anything back. **A reproduction that omits the thing
under test proves nothing about it**, and this one was confident and wrong for
about twenty minutes. The behavioural check agrees: twenty rounds of PUT then an
immediate GET against the real admin entrance and the real gateway, zero stale
reads and zero stale routings.

**And it does not reproduce here at all.** Thirty direct rounds, one full-stack
run, then five more against a Postgres throttled to 0.4 CPU: no failure. The
throttle was aimed at the wrong thing — the whole test takes under two seconds,
so the database is not the bottleneck. What CI has is contention across the
*set*: two cores shared by Postgres, two uvicorns, the fake runtime, Next and
Chromium, which is why the PUT there took 82.6 ms against 7.2 ms here.
Reproducing that on this machine means loading a node that is serving, so it was
not done.

**So the next failure gets instrumented instead of re-argued.** Two changes,
both test-side, neither touching the application:

- The full-stack harness runs uvicorn at `--log-level info` rather than
  `warning`, which is what turns the access log on. Verified: a run now prints
  `PUT /admin/routing-policies/chat 200` and the `GET` that follows it. There
  was no server-side record of either request before, and the re-run had already
  overwritten the failing attempt's job log by the time it was wanted.
- On failure the assertion polls the chat policy from **both sides** for three
  seconds — straight to the admin entrance, and through the Next origin the page
  itself uses — and attaches the timeline. The pair names the layer: direct new
  and proxied old puts it in front of the backend; both old then new gives the
  size of the window; both old and staying old means the PUT's 200 described
  something it never persisted.

The diagnostic was itself exercised rather than assumed to work: the assertion
was temporarily pointed at a locator that cannot match, the run failed, and the
attachment came out with both readers agreeing at +0 ms and +283 ms. Then it was
put back and the suite passes.

**One thing found on the way and not fixed:** the admin API sends no
`Cache-Control: no-store`. It is not the cause here — that was checked and
excluded above — but an API that returns management data and does not say it
must not be stored is its own small gap.

### The backup section 9.4 had described since the first draft now exists, and the ordering argument it needs was wrong in my first pass

Nothing implemented it. `grep -ri backup` over the whole repository returned one
comment in `docker-compose.yml` and the design in security.md §9.4 — so a
platform holding the team's unpublished research had no copy of it anywhere,
and had not had one for the twenty-five days it had been serving. It was the
last Phase 2 functional item and the only one that had never even reached
"marked done".

What shipped: `launchd/backup.sh`, `launchd/online.rcsl.backup.plist` firing it
at 03:30, check 15 of `check-platform-health.sh`, and
[runbooks/restore.md](../runbooks/restore.md). One nightly restic repository
holding the database, the `documents` volume, `secrets/` and a manifest.

**§9.4 left four questions open and none of them was a typing problem.**

- **`prompt_logs` is out.** §9.4 offers two ways to bound it — exclude the
  table, or keep backups for less time than the dataset does — and only one is
  available, because the dataset's bound is a *ceiling* of 30 days on a default
  of 7 and a backup retention under a week is not a backup. The argument that
  actually settles it is cheaper than the one the section sets up: the rows have
  no recovery value. A transcript exists for the length of a debugging session,
  and nobody restoring from a disaster wants a three-week-old one. It is
  `--exclude-table-data`, not `--exclude-table`: dropping the table would
  restore a database missing one `RouteChatRequest` writes to, so the first
  request after a successful-looking restore would fail. The rehearsal in the
  runbook asserts `prompt_logs` is both present and empty, which is the only
  place that distinction can be caught.
- **`refusals` is in, under the other option.** Retention is 7 daily, 4 weekly,
  3 monthly, and the figure first written for it here was wrong. It said "about
  ninety days"; running the policy against 130 synthetic daily snapshots kept 11
  of them and spanned **49 days**, because the monthly leg counts calendar
  months rather than 30-day windows and therefore oscillates from about 32 days
  on the first of a month to about 92 on the last. The bound that has to hold is
  the upper one against that dataset's own 180-day ceiling, and it holds with
  more room than the guess claimed.
- **`secrets/` is in the repository**, and it is the largest decision here.
  Leaving it out produces something that is not a restore: `totp_encryption_key`
  is what every stored TOTP secret is encrypted under, `api_key_pepper` is what
  every key hash is peppered with, and without them the restored database is one
  where every administrator is locked out and every key is dead. So the question
  was never safe against unsafe — it was one item kept off this machine or
  sixteen, and one is the number that will still be right in a year. What it
  costs is written in three places rather than one, because it is the sentence
  most likely to be skipped: the repository password plus read access is the
  whole platform.
- **Qdrant is out and rebuilt.** It is derived, and `qdrant_store.py` derives
  point ids rather than generating them, so a re-index is idempotent. The cost
  is every document embedded again, and the runbook carries the loop instead of
  leaving it as an exercise.

**The ordering argument was wrong the first time I made it, and the direction it
was wrong in is the interesting part.** The obvious rule is "files first, then
the database", so that a restore can only ever have a spare file rather than a
row pointing at nothing. That is backwards. `knowledge_documents` rows point at
files in the `documents` volume, and the two capture moments can disagree in two
ways, not one: a document *uploaded* between them leaves a row with no file if
the files went first, and a document *deleted* between them leaves a row with no
file if the database went first. Uploads and deletes cut in opposite directions,
so no ordering is safe against both — an ordering can only choose which failure
is the common one. The database goes first, because uploads are ordinary and
deletes are rare, which puts the harmless shape (an orphan file, invisible) on
the common path.

The residue is not papered over, and that is the part worth keeping. The runbook
ends with a reconciliation — two `comm` calls against the row list and the
directory list — so the rare inconsistency arrives as a named list on the day of
the restore rather than as a document that mysteriously 500s six months later.
Making the window genuinely atomic means stopping the stack nightly, and a
platform that stops serving every night to protect data it is not serving is a
worse trade. Worth noting that the live system already produces the same shape
transiently and on purpose: `ManageKnowledge._forget_document` deletes the bytes
before the row, so a half-finished delete leaves something the operator can see
and retry.

**Two controls exist only because the failure they prevent looks like success.**

The script refuses to `restic init`. A typo in the repository path, or a disk
that mounted somewhere slightly different, would otherwise open a fresh empty
repository, and every night after that would succeed against it while the real
history sat elsewhere. For the same reason there is a separate check that
something is actually *mounted* at `/Volumes/nexus-backup`: on macOS an
unmounted external disk leaves an ordinary empty directory at its mount point,
so without that check the nightly job would quietly grow a second complete
repository on the boot volume and report success every time.

**And one of those failures was in the first draft of this change.** The
manifest was passed to `restic backup` as a host path under a `mktemp -d`
directory — a different name on every run. `restic forget` groups snapshots by
host and path, so every night's manifest would have been a group of one, every
group would have satisfied `--keep-daily 7` on its own, and **nothing would ever
have been pruned**: the retention policy that is the entire justification for
`refusals` being in the backup would have been true of the snapshot listing and
false of the data, for about ninety days before anyone could notice. It is a
`--stdin` snapshot at a fixed path now, which is also why the database and
documents captures use a constant `--stdin-filename` rather than a dated one.

**Check 15 splits across the two tiers rather than sitting in one.** No backup
ever, no success ever, or no success in 72 hours are tier 1 and mail
immediately; 30 to 72 hours, and a single failed run on top of a fresh success,
wait for the digest. The file's own header argues that anything with lead time
belongs in the digest because a subject line reading FAILING for a fortnight
stops meaning anything — and a broken backup does not have lead time in that
sense. Nothing is going to repair it, and its cost is not paid gradually but in
full, once, on the day somebody needs it. The state file keeps the last success
and the last outcome on separate lines precisely so those two cases can be told
apart. All seven branches were exercised against synthetic state files before
this was written down.

**It was installed and rehearsed the same evening, on the Mac Studio, against
the live stack.** restic 0.19.1, and the repository is on the **internal disk**
at `/Users/Shared/nexus-backup/restic` because `diskutil list external` was
empty: it shares a failure domain with the data it copies, so it defends against
a bad migration, a mistaken `docker volume rm` and a deleted collection, and not
against the disk. That is written into `backup.sh`, the runbook and §9.4 rather
than only here, because it is the sentence most likely to be forgotten. Moving
it is two constants and one `restic init`.

First backup at 21:59:59: four snapshots, 67,080 bytes of raw data. The
LaunchDaemon was bootstrapped the same evening and `launchctl print` confirms
what the plist intended: `type = LaunchDaemon`, calendar interval 03:30,
`username = rcslmac1` (which it needs for the docker socket and for `secrets/`),
the working directory and both log paths, `nice = 5`, and `state = not running`
because `RunAtLoad` is false on purpose.

**Then it was kickstarted, because "works by hand, fails as a daemon" is the
shape of most of the eight defects 2026-07-26 found**, and both successful runs
up to that point had been from an interactive shell. Under launchd — root
starting it, dropping to `rcslmac1`, launchd's own environment, no terminal —
`runs = 1`, `last exit code = 0`, every stage logged, and the state file written
`ok` at 22:10:51. That run also produced the first evidence that `forget` is
actually working the way the grouping was designed for: it added four snapshots
to eight and left eight, two per path group, which is the newest plus restic's
pinned oldest. Had the manifest still been going in under a `mktemp` path, that
number would have been twelve. No stray watchdog process survived the run
either, which is the other half of the defect above. The rehearsal, in full:

- The dump — 2,285 lines — restored into a throwaway `postgres:17-alpine` under
  `ON_ERROR_STOP=1` with exit 0 and no errors, and **every count matched the
  live database exactly**: 8 users, 32 API keys, 6 models, 697 usage records,
  301 audit rows, 11 refusals.
- **The `prompt_logs` exclusion was proven independently of the table happening
  to be empty**, which matters because it *was* empty and the obvious check
  could therefore only return one answer. `CREATE TABLE public.prompt_logs` is
  in the dump and `COPY public.prompt_logs` is not. The control is
  `knowledge_documents`: also zero rows, not excluded, and its `COPY` block is
  present. So the absence is the flag working, not the emptiness.
- All **17** secret files came back byte-identical, and no `*.example` or
  `README.md` leaked into the snapshot.
- **The documents capture had no payload to prove, so it was proven separately.**
  The knowledge base holds zero documents, so `documents.tar` was two directory
  entries — a result that cannot distinguish "the capture works" from "the
  capture silently produced nothing". A 4 KiB random probe was written into the
  live volume at `.backup-selftest/`, a path the app provably cannot address
  (`_TENANT_ID` is `[A-Za-z0-9_-]{1,64}`, so a name containing `.` is not
  constructible), pushed through the real pipeline into a throwaway repository,
  and came back with an identical sha256. The probe was removed and the volume
  is back to its single `default/` directory.
- **Check 15 was verified against reality rather than only against synthetic
  state files.** It fired tier 1 at 21:46:54 with `backup-never-run` and mailed
  both recipients — a correct alarm, since the platform genuinely had no backup
  at that moment, and worth recording that it reached two people's inboxes
  before anybody had been told the check existed. It cleared by itself at
  22:02:02 with a recovery mail once the first backup succeeded. The whole
  lifecycle, on the real mail path.

**Two defects were found by doing this rather than by writing it.** The watchdog
was `( sleep 7200; kill -TERM $$ ) &` with a `kill` in the exit trap, and it was
wrong twice: the subshell inherits stdout, so `bash backup.sh | tail` hung for
two hours against a script that had already finished, and `kill $WATCHDOG` kills
the subshell while orphaning the `sleep` it was supposed to end — two of them
were still running when this was found. It polls `kill -0 $$` every 30 seconds
now and ends by itself. And the retention figure was a guess that measurement
corrected, recorded above.

**What is not done, and is why the roadmap box stays `[~]` even with the
rehearsal passed.** The repository is on the same disk as the data, so the item
as the roadmap words it — a backup — is not honestly `[x]` until it is on
separate hardware. And it is one repository, not 3-2-1: the offsite leg is blocked on a question this end cannot
answer — whether institutional policy and the collaboration agreements permit
unpublished research data on third-party cloud storage — and writing it in
before somebody answers would have made it the ninth designed-and-not-in-force
control this file records.

### The browser now drives the two authentication state machines

Vitest had reached components, but the browser still drove nothing. That left
the exact boundary where authentication had already failed once — React
reconciling the password form's controller into the TOTP form and dropping every
typed digit — covered only through jsdom. Playwright now drives two Chromium
paths against the real Next.js pages: password then TOTP, including the identity
refetch before the redirect; and invitation enrolment through password, TOTP QR,
account creation and the recovery-code acknowledgement that gates leaving the
only copy of those codes.

The admin responses are intercepted at the browser's network boundary rather
than provided by a shared database. That is deliberate and bounded: these tests
assert accessible names, request bodies, state transitions and navigation, while
the backend integration suite continues to prove the same authentication flows
against real Postgres and Redis-shaped ports. A browser test does not become
more end to end by making its account state depend on whichever CI run arrived
first.

CI installs Chromium, runs the paths, and retains the HTML report, trace and
screenshots. The first local run also found an infrastructure defect in the
test runner itself: both tests finished, but Playwright's `webServer` teardown
left Next's worker alive on Windows, so the command never returned. A small Node
coordinator now owns both children and terminates the whole server process tree
(`taskkill /T` on Windows, a detached process-group signal on POSIX). The same
two tests pass and the command exits in 18 seconds instead of timing out after
reporting success.

### API key management now has a complete browser path

The next Playwright path drives the first day-to-day management workflow:
issue a key, acknowledge the one-time plaintext before the dialog can close,
edit its name and rate limit, revoke it, and reveal it again through the
revoked-key filter. The intercepted admin API is stateful for this test, so the
list after every mutation is derived from the request the page actually sent;
the test asserts the POST and PATCH bodies rather than merely changing the DOM.

This is still a browser-boundary test, not a full-stack claim. The backend
integration suite already drives the same create, update, and revoke endpoints
against real Postgres, while the Playwright path proves the Next.js pages,
accessible controls, query invalidation, single-display secret guard, and
permission-gated actions. A local Docker daemon was unavailable during this
increment, so no CI-only database orchestration was added without a way to run
it first. A unified browser-to-Postgres harness remains useful when that local
precondition is available; routing-policy-to-gateway behaviour and stream
cancellation were the next browser increments.

### Routing edits and stream cancellation are browser-driven too

The fourth path edits the existing chat routing policy through the real form:
it changes deliberation, replaces one model, adds a second candidate with
structured requirements, asserts the complete idempotent PUT body, and proves
the table was populated by a GET made after that save. The fifth path uses a
real local SSE socket rather than a finite intercepted response. It receives a
partial answer, stops it while preserving what arrived, then starts another and
leaves through a client-side Next.js link; both routes must close the upstream
connection so neither generation keeps a model concurrency slot.

Three independent adversarial reviews then attacked the tests and runner. They
found two immediate failures (an ambiguous repeated-candidate checkbox and a
Next dev overlay alert mistaken for an application error), plus four ways a
green run could still lie: document-level navigation cancels fetches even if
the hook's unmount cleanup is absent, the SSE fixture shared state across
parallel workers, write mocks omitted the CSRF cookie/header contract, and the
runner could mistake an old process on a fixed port for the Next child it had
just started. The corrected runner chooses an unused loopback port, owns both
Next and Playwright process trees through signals and spawn errors, and
namespaces SSE state per test case. Five browser paths pass; the chat case also
passes twice concurrently under two workers.

### The browser meets a production build, which found a sixth way to lie

Review of the pull request raised a seventh: everything above ran against
`next dev`, which is an application nobody deploys. The evidence was already in
the tests — one had to ignore a development-overlay alert, another to allow
twenty seconds for a cold compile — and dev mode cannot exercise anything
decided at build time, which is where `NEXT_PUBLIC_*` inlining and the *absence*
of StrictMode's double-invoked effects live.

The runner now builds before it tests. That build immediately failed the
routing-policy path, and the reason is the interesting part. Base UI portals a
select's popup to the document body and leaves it mounted, still sized, after it
closes; the test asked the whole page for an option by accessible name. With two
candidate rows offering the same aliases, the same name exists in two lists at
once, so the click resolved into the row the test had already finished with.
Under `next dev` this never fired: every preceding step was slow enough that the
previous popup had always gone. A test whose correctness depended on the
application being slow is precisely the kind of green that a dev-mode run
cannot distinguish from a real one. Each choice is now scoped to the list its
trigger names through `aria-controls`, after waiting for that trigger to report
itself open — the click returns before the popup exists.

Two smaller corrections came with it. `failOnFlakyTests` is on in CI, because a
test that fails and then passes was leaving a green tick and saying so only in a
report nobody opens, and intermittent is the *interesting* result for assertions
about cancellation and CSRF. And the e2e build writes to `.next-e2e`: it has a
test CSRF cookie name inlined into its client bundle, which must not be able to
land in something a person could mistake for a deployable build. The runner's
deadlines are now five minutes for the build and ten for the tests, with CI's
step deadline one minute above their sum so that a hang is reported by the
runner, which can say which half stalled.

Five paths pass against the production build, in less time than the dev-mode
run took, and `--dev` remains for local iteration.

This still does not claim that editing the policy changed gateway selection.
That needs the browser, admin API, Postgres, gateway and a controllable runtime
in one harness. The current policy path proves the management UI contract; the
existing backend integration tests prove persistence; their behavioural join
remains the Phase 3 increment.

**Correction, 2026-08-18: that join closed on 2026-08-10.**
`e2e/full-stack/routing-selection.spec.ts` and the CI job that runs it drive the
real admin entrance, the real gateway and a Postgres rebuilt from Alembic, and
observe a policy edit changing which model the gateway asks its runtime for. The
sentence above was true when written and was still being quoted as current eight
days later, which is what a present tense inside a dated entry costs.
