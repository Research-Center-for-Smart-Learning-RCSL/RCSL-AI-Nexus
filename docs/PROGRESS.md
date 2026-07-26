# Progress Log

What has actually been built, in the order it happened, and what was learned
doing it. Newest first.

This is the narrative record. Two other places describe state and neither
replaces this one:

- [`ROADMAP.md`](./ROADMAP.md) is the plan, item by item.
- [`architecture/security.md`](./architecture/security.md) section 13.0 is a
  checked control-by-control inventory of what exists.

If those two disagree with this file, they are wrong: update them here first
and propagate. The reason for saying so is that they have already drifted once.

---

## 2026-07-26

### The container bring-up path ran 51 seconds into the boot, and that same boot falsified a number the reboot argument rested on

**§1.1b was run and it passed on the first attempt.** The script refused nothing, stopped the
nine services at 21:50:38, the machine was rebooted by hand, and the reconciler brought the
whole platform up on the boot that followed. The four expected lines came out in order and
nothing else did. The row that seven natural boots and one address injection could not fill is
filled.

| Time | Event |
|---|---|
| 21:50:37 | preconditions pass; the guard reads the *previous* boot's reconcile correctly (`ran 7s into this boot`) |
| 21:50:38 | nine services stopped, read back and confirmed |
| 21:51:23 | boot (`kern.boottime`) |
| 21:51:30 | `reconcile starting` — 7 seconds into the boot, the same as §1.1a |
| 21:51:45 | `tailnet address present` (15s wait) |
| 21:51:46 | `docker daemon responding` |
| **21:52:01** | **`not running:` all nine → `docker did not restore the stack; bringing it up`** |
| **21:52:14** | **`stack up: all expected services running` → `all published bindings intact`** |

**Boot to recovered: 51 seconds.** Script to recovered, which is the real outage window: 1
minute 36 seconds. §1.1a's was 2m55s from boot, and that comparison is the point of the whole
exercise — this fault is cheaper in every dimension including the one that matters to whoever
is using the platform.

**Docker Desktop restored exactly zero of the nine, which is the mechanism the test rides on.**
`restart: unless-stopped` promises this and the compose file has said so all along, but until
now nothing had watched the *unless* survive a reboot on this machine. It did, completely: the
missing set was all nine on the first sample and all nine on the last.

**The settle loop hit its structural floor, and that retires a worry §1.1a raised.** It took 15
seconds — four samples with three five-second sleeps between them, which is the minimum the loop
can take and still be the loop. §1.1a measured 27 seconds for the same code against a healthy
boot's 16, and the open question was whether the loop is expensive at boot. It is not: what was
expensive was inspecting a *running* stack while everything else on the machine was moving.
Against an empty one the four `docker compose ps` calls cost nothing measurable. The same
contrast shows in the scan — 40 seconds in §1.1a, absent here because there were no running
containers to sweep.

**Of the 44 seconds the reconciler spent, 31 were waiting and 13 were working**: 15s for the
address, 1s for the daemon, 15s for the settle loop, 13s for `up -d` to take nine services from
nothing to all-running including the postgres health gate and `migrate` running to `Exited (0)`.
The one hand test of this path took 16 seconds for a single already-imaged service, essentially
all of it the settle loop; the bring-up itself is what boot conditions were never measured
against, and it costs 13 seconds.

**The last line was `all published bindings intact`, exactly as predicted before the run.** No
`can't assign requested address` appears in the Docker backend log for this boot — the newest
such lines are still §1.1a's trio at 21:02:56 — because the reconciler waits for the address
first, so by the time `up -d` ran the address had been on the interface for 16 seconds and the
forwards were built correctly the first time. The two injectors test two paths and neither
substitutes for the other; this run is the evidence for that rather than the assertion of it.

**The monitor stayed silent, and only half of that was by design.** Boot grace covered
21:51:23–21:55:23, so the `RunAtLoad` run was suppressed and the 51-second recovery finished
well inside it; the first real check was 21:56:30, which is also the worst-case detection
latency had the reconciler failed — about five minutes, not the ten quoted for §1.1a, because a
240-second grace against a 300-second interval suppresses exactly one run. But the platform was
also down for the 45 seconds *before* the reboot, and nothing guarded that: the previous boot's
schedule had fired at 21:47:43 and would have fired next at 21:52:43, by which time the machine
was gone. **That was luck of timing, not a control.** Run the script a minute later in the
interval and the monitor mails a true `failing` — correctly, since the platform really is down.
The runbook now says so; it is not a failure of the test.

**One accidental confirmation, recorded because it could otherwise be misread.** The full check
was run by hand at 21:53:29, 126 seconds into the boot, and exited 0 having checked nothing —
it took the boot-grace path and rewrote the state file, which is what that path is for. It was
rerun at 21:56:35, outside the grace, and *that* is the pass: exit 0, nine services, six
bindings requested-equals-actual, six entrances 200, no state change. An `exit 0` inside the
grace window is not evidence about the platform.

**The boot also settled an open prediction that had nothing to do with why it was run, and half of it was wrong.** The netmap alternation model predicted the next boot would miss the disk cache and take 9 seconds to bring the address up. It missed the cache — the fifth consecutive confirmed prediction, which is where load-without-rewrite stops being provisional — and the address took **11 seconds**, not 9 (`tailscaled` 21:51:30, `peerapi` on 100.108.250.62 at 21:51:41). Cache-miss boots therefore measure 9, 9, 9, 11, 17, not a constant, and the runbook's "no spread at all" was three samples mistaken for a value. That number was load-bearing: the argument for injecting rather than rebooting ran `10.3 − 9 = 1.3s` and concluded the margin *cannot* go negative. It can — though the honest version of the correction is weaker than the arithmetic suggests, because `10.3 − 11` subtracts the extremes of two distributions measured on different boots, and this boot produced no margin observation at all since Docker bound nothing. What survives: the margin distribution is wider than three samples made it look, 16:45's 17-second address is the top of that distribution rather than a retired outlier, and "rebooting cannot lose" was overstated. The conclusion is unchanged and better grounded — inject because a 90-second hold is repeatable, not because rebooting is guaranteed to win.

**And the reconciler is not a stopwatch.** Its log says the address took 15 seconds; it samples every 5. Both this and §1.1a's off-by-one were the same mistake in different clothes — reading a number off an instrument built for a different question. Address timings belong to `tailscaled`'s log.

**What this does not establish is unchanged from what was written before it ran.** It does not
show Docker Desktop's restore failing on its own — that happened once, after the macOS 26.5.2
update, and why is still unknown; the state is reproduced, not the cause. And it does not
replace round two, which tests the update reboot as a whole: automatic login, `pmset
autorestart`, and what Docker does afterwards. None of those were touched.

---

### The second repair path turned out to be injectable too, and the claim that it was not was mine

**Yesterday's entry and three other files said the container bring-up path could only be
filled by rerunning round two, because the injector "withholds the address, not Docker
Desktop's restore". The first half of that is true and the conclusion does not follow.** The
mechanism was sitting in `docker-compose.yml` the whole time: every long-lived service carries
`restart: unless-stopped`, and the *unless* is the entire lever — a container that was
explicitly stopped is not restored when the daemon comes back. Stop the stack, reboot, and
Docker Desktop faces nine containers it will deliberately leave alone. The reconciler then
wakes to exactly what the 19:09 boot left it: everything present, nothing running.

**`launchd/stop-stack-once.sh` and runbook §1.1b.** It is a hand-run script with no plist, and
that absence is deliberate: §1.1a needed a boot-time job because its fault had to be injected
*during* boot, whereas this fault is set beforehand and simply persists, so a plist would be a
moving part with nothing to do.

**It is an order of magnitude cheaper than §1.1a, which is the point.** The host stays on the
tailnet for the whole window — SSH, `tailscale serve`, everything — so no person has to be at
the machine and a failed test is recoverable from anywhere with `docker compose up -d`. The
cost is that the platform is down from the moment it runs until the next boot recovers it.

**Most of the script is refusals, and one of them is the reason the rest can be trusted.** It
declines to run if §1.1a's plist is installed (both faults at once blocks each one's recovery
path), if the nine services are not all running, if any requested binding is already unbound,
if the reconciler's plist is missing — and, the one that matters, **if the newest
`reconcile starting` in the log is older than the current boot**. A plist on disk is a
necessary condition that proves nothing about whether launchd loaded it, and rebooting with
the stack down and nothing scheduled to raise it is the single way this injection becomes an
outage rather than a test. The log answers the question actually being asked — did this daemon
run on *this* boot — and that is evidence rather than configuration. After stopping it reads
the result back, because a half-stopped stack would have Docker restoring some containers and
the reconciler meeting a set that is neither empty nor complete: a fault nobody designed.

**Eight branches were run rather than read**, against the live platform without ever stopping
it: all five refusals fired, the healthy-precondition path passed, the success path printed
its instructions, and the half-stopped guard caught a stop that had been replaced by a no-op.
The one branch not separately exercised is the already-unbound refusal, which is the same six
lines as in `check-platform-health.sh` and `reconcile-port-bindings.sh`.

**What it will and will not prove, stated before it is run so the result cannot be read
generously.** It will show the reconciler bringing the platform up at boot, with everything
moving at once — the part a hand test cannot reproduce, and §1.1a measured how much that
matters: the same code that settles in 16 seconds on a healthy boot took 27, and a scan that
finishes inside a second took 40. It will *not* show that Docker Desktop's restore fails on
its own; that happened once, after the macOS 26.5.2 update, and why is still unknown. It
reproduces the state, not the cause — §1.1a's limit exactly. And it does not replace round
two, which tests the update reboot as a whole: automatic login, `pmset autorestart`, and what
Docker does afterwards. None of those are touched here. The expected outcome is the third row
and only the third row: `all published bindings intact`, not `OK: all bindings restored`,
because the reconciler waits for the address before it runs `up -d`.

---

### The injected boot filled the row seven boots could not, and settled two things the last entry left open

**§1.1a was run and it passed on the first attempt.** The plist went in, the machine
rebooted at 21:02:36, and the injector deleted its own plist and held `tailscaled` down
from 21:02:43. Docker Desktop bound at **21:02:56** — seventy-eight seconds before the
address existed — and failed on exactly the three services that name it, `:8000`, `:3001`
and `:8002`, no more and no fewer. The reconciler waited the hold out, saw the address at
21:04:14 (one second after the release), found all three bindings dropped, and logged
`recreating: admin-public frontend-public gateway` → **`OK: all bindings restored` at
21:05:31**. Afterwards: nine services running with `migrate` at `Exited (0)`, all six
requested bindings equal to actual, all six entrances at 200, Ollama on loopback and
nothing on the tailnet address, and the plist gone. The row that stayed blank for seven
boots is filled, and it is filled with manufactured weather rather than a boot that lost
the race on its own — that second claim still rests only on 16:45.

**The margin was −78 seconds against a natural ceiling of +1.3.** That is the ninety-second
hold doing what it was sized to do, sixty times over, and it is the whole reason the row
could be filled at all.

**The repair costs about twice at boot what it costs by hand, which is the part the hand
test could never have told us.** The named-set precondition took 27 seconds against a
stable 16 on four healthy boots; the binding scan took 40, with twelve seconds between each
of the three detections, where on a healthy boot the identical scan finishes inside one
second. `broken_services()` has no sleep in it, so that is pure `docker inspect` latency on
a machine that is still busy. Of the 77 seconds from address to restored, more than half
was spent looking rather than repairing. "Its cost is stable at sixteen seconds" was a
statement about healthy boots only.

**The boot grace suppressed a real failure for the first time, and it was right to.** For
the 2m35s between 21:02:56 and 21:05:31 the platform was genuinely broken and no mail went
out, because all of it fell inside the window the reconciler owns. That is precisely the
behaviour the grace was written for, and it had never once been exercised: before 20:45 the
greedy `sed` meant it could not fire at all, and after the fix there had been no failing
boot. Had the repair failed, the 21:07:43 run would have caught it — worst-case detection
is ten minutes.

**And the fix that was "tested in parts" is now tested whole — but not by the evidence the
last entry said to look for.** That entry predicted "a state mtime within seconds of boot
and no mail". The mtime half of that is unusable: `StartInterval` counts from load either
way, so the first scheduled write lands at load+300 whether `RunAtLoad` fired or not, and it
overwrites the boot-time write. The unified log does separate them — four spawn/exit pairs,
21:02:43.356→.473, 21:07:43.678→44.286, 21:12:44.309→.838, 21:17:44.858→45.386. The first
ran at an uptime of seven seconds and finished in **117 milliseconds** against 528–608ms for
the three full-path runs, and the full path cannot be done in a tenth of a second: six curl
probes, a `docker info`, a `docker compose ps` and ten `docker inspect` calls. Exit 0, no log
line, no mail. `launchctl print`'s `runs` counter was the first instrument reached for and it
is the wrong one — it carries no timestamp, so `runs = 3` cannot be distinguished from
`RunAtLoad` plus two intervals without separately recovering when it was read.

**The 240-second grace turned out to have been chosen with seven seconds to spare.** The
first scheduled run of that boot fired at an uptime of 307 seconds. At the old grace of 300
it would have evaluated by seven seconds; eight seconds more launchd latency on the same
healthy machine and it would have been skipped, pushing the first real check to ten minutes.
The coin flip that argument was built on has now been observed landing, close to its edge.

**A check that came back clean was a false negative, for the third time in one day and the
second time from log rotation.** `grep "can't assign requested address"` over
`com.docker.backend.log` returned nothing, which reads as "the injection did not work". The
three lines are in `com.docker.backend.log.20260726-210850.988`: Docker rotated the file at
21:08:50 and the grep ran around 21:09. The runbook now specifies the glob. This is the same
shape as the 20:12:32 rotation noted in the previous entry and as `tailscale status --json`
answering a question it had no field for — a check whose scope is smaller than it looks,
read as a statement about everything.

**Finally, the netmap cache model took its first exception, from the rehearsal rather than
the test.** Before injecting, `tailscaled` was restarted by hand to confirm §1.1a's recovery
command works. It came up at 21:00:27 on `netmap cache is not available` — thirty-one minutes
after the 20:29:15 write that the model says should have been waiting for it. A TTL does not
explain it, because 18:08:23 wrote and 19:10:00 loaded sixty-one minutes later. The one clean
distinction is that this was a daemon restart inside a running session and every recorded hit
followed a reboot; so either the model is wrong or restart and boot are different events for
this cache, each with one observation. Until they are separated the alternation applies to
boots only. The standing prediction — that the boot after 20:29 would be fast — was never
tested, because the injector held `tailscaled` down through it; the daemon that started at
21:04:13 loaded the 21:00:30 cache and logged no rewrite, making load-without-rewrite four
observations and predicting a **cache miss on the next boot**.

**The injector misreported its own measurement, and that is now fixed.** It logged
`tailnet address ... is back within 10s of the release` for an address the reconciler had
independently seen one second after the release. It printed the loop counter times five,
which charges the sleep *following* each check to the check itself — five seconds of
off-by-one on top of five seconds of polling granularity. A tool whose entire purpose is
measurement, wrong on the one line of it that is a number. It now measures elapsed seconds
and polls every second; both branches, address-present and address-absent, were run rather
than read.

**Writing that count down found the runbook had been over-reporting it.** §1.1 said "round
one has passed six times" in three places. Six is the number of *attempts* — 16:45, 17:21,
18:08, 19:43, 20:24, 20:29 — and the first of them is the failure the whole reconciler exists
because of, so it cannot also be a pass. Round one has passed **five** times out of six. The
file could already have caught itself: it labels 19:43 "round one's fourth", which only adds
up if 16:45 was the first. The error is small and it runs in the direction that flatters the
record, which is the direction worth being suspicious of.

**What is still blank.** The container bring-up path has never run at boot, and the injector
cannot produce it — it withholds the address, not Docker Desktop's restore. That row needs
round two rerun. Round one stands at five passes in six attempts; round two remains one run,
failed. The injected boot is not a round-one pass: it is a boot deliberately made to fail,
which then recovered.

---

### Two more boots proved the lever cannot work, and the liveness record had a hole where it is read

**Round one was run a fifth and sixth time, back to back, and both passed on the
first outcome.** 20:24:21 and 20:28:58, 4m37s apart, hands off both times. Nine
services running with `migrate` at `Exited (0)`, all six requested bindings equal
to actual, all six entrances at 200, Ollama on `127.0.0.1:11434` and nothing on
the tailnet address, `all expected services running` → `all published bindings
intact` on both. The named-set precondition decided in sixteen seconds both times,
the same as 19:43 — its cost is stable.

**This was the runbook's own lever, pulled deliberately, and it failed.** The
instruction was to reboot twice and watch the second, because a boot that loads
the netmap cache does not rewrite it and hands the next boot the slow path. The
mechanism worked exactly as described: 20:29 found no cache, waited 9 seconds for
the address, and its margin fell from 8.3 seconds to 1.4. It still won.

| boot | `tailscaled` start | address usable | Docker's `exposer.Add` | margin |
|---|---|---|---|---|
| 16:45, failed | 16:45:15 | 16:45:32 (+17s) | 16:45:29 | **−3s** |
| 17:21, passed | 17:21:48 | 17:21:48 (+0s) | 17:21:59 | **+11s** |
| 18:08, passed | 18:08:14 | 18:08:23 (+9s) | 18:08:25 | **+2s** |
| 19:09, failed for another reason | 19:09:59 | 19:10:00 (+1s) | *never* | *no race* |
| 19:43, passed | 19:43:28 | 19:43:37 (+9s) | 19:43:39.7 | **+2.7s** |
| 20:24, passed | 20:24:22 | 20:24:24 (+2s, cache hit) | 20:24:32.3 | **+8.3s** |
| 20:29, passed | 20:29:06 | 20:29:15 (+9s, cache miss) | 20:29:16.4 | **+1.4s** |

**And the reason it will keep winning is now arithmetic rather than hope.** The
claim that Docker is the stable side at 11 to 14 seconds was the small sample
talking: the six boots where it bound are 14.0, 11.0, 11.0, 11.7, **10.3**, **10.4**
seconds, and the two lowest are the two newest. Cache-miss boots, meanwhile, put
the address up at exactly 9 seconds — three observations, zero spread. `10.3 − 9`
is the entire protection, so the lever's ceiling is a 1.3-second margin and it
cannot go negative. Only 16:45 ever lost, on a 17-second address that has not
recurred in six boots. **Rebooting repeatedly is not a test, it is waiting for
weather.**

**The netmap model made its third and fourth predictions and both held, so the
alternation is now seven boots with no exception.** 19:43 wrote, so 20:24 loaded
(+2s) and logged no write in its session; 20:24 loaded without rewriting, so
20:29 missed, waited 9 seconds and wrote at 20:29:15. Load-without-rewrite rests
on three observations now (17:21, 19:09, 20:24). Next boot is a fast one.

**So the blank row gets filled by injecting the fault.**
`launchd/delay-tailscaled-once.sh` and its plist hold `tailscaled` down for 90
seconds at boot — six times the margin Docker needs to lose by — so Docker binds
before the address exists and the reconciler has to walk the binding repair path
with everything else at boot moving at the same time, which is the part a hand
test cannot reproduce. It is a test tool and is deliberately not in the runbook's
install list. Two properties are the ones that matter: it deletes its own plist as
its very first action, before anything that can fail, so whatever happens it
affects exactly one boot; and it uses `launchctl bootout`/`bootstrap` rather than
`tailscale down`/`up`, because `up` can reset prefs not named on the command line
and the prefs here include Tailscale SSH — the remote access path. The residual
risk is stated rather than engineered away: the release runs from a trap covering
EXIT, INT, TERM and HUP but not SIGKILL, and during the hold the host is off the
tailnet entirely, so this is a with-a-person-at-the-machine procedure. Runbook
§1.1a.

**Then the monitor's own liveness record turned out to have a hole exactly where
the runbook reads it.** The state file's mtime is the only evidence the daemon is
alive — the log is events-only — and the criterion is "under five minutes old".
With the plist at `RunAtLoad=false` and a 300-second interval, *no run happened in
the first five minutes of a boot*, so the freshest mtime in that window predated
the boot: three to eight minutes old, depending only on where the reboot fell in
the previous interval, against a five-minute criterion. The runbook tells the
operator to wait two or three minutes after a reboot and then check exactly this.
These two reboots demonstrate it: no run happened across either of them, and the
20:26 check passed with thirteen seconds of margin, by luck. This is the second
wrong version of this one criterion — the first said "mtime within ten minutes of
boot" — and both were wrong in the same direction, describing when the file gets
written rather than what the reader needs to know.

`RunAtLoad` is now true, and the boot-time run is suppressed by the boot grace,
which rewrites the state file verbatim and exits: the signature is unchanged
because nothing was checked, so it cannot mail, and the only thing it updates is
the one thing it is entitled to claim — *this ran, and deliberately asserted
nothing*. If the file did not exist it writes the empty-signature sentinel, so the
first real run still mails `baseline` and not a false `recovered`.

**The boot grace it now relies on had never once fired.** It parsed
`sysctl -n kern.boottime` — `{ sec = 1785068938, usec = 428375 } ...` — with
`s/.*sec = \([0-9]*\).*/\1/`, whose leading `.*` is greedy and matched through to
`usec`. `BOOT_SEC` was the microseconds field, uptime came out as the whole Unix
epoch, and the comparison could only ever answer "not in grace". **That is the
fourth instance of this log's recurring defect, and this time it was inside the
check whose entire job was to have two answers.** It also put a nine-digit
`uptime` line in every alert mail sent before the fix, including the 19:15 one.
`RunAtLoad=false` had been load-bearing by accident: it was the only thing
actually suppressing the boot-time run. The pattern is anchored at the start of
the line now, and the grace is 240 rather than 300 so it sits clearly below the
interval instead of on the boundary, where whether the first scheduled run of a
boot evaluated or was skipped came down to how many seconds launchd took to load
the job — a coin flip deciding whether the first real check is at five minutes or
ten.

All three paths were run rather than read: the grace path rewrites the file
byte-identically with a fresh mtime and exits 0 silently; the normal path still
evaluates fully and mails nothing when the signature is unchanged; and with no
state file at all the grace path writes the `\n0\n` sentinel that reads back as
"no previous state".

**Two of those three were forced rather than observed, and the distinction is the
same one §1.1 makes about the reconciler.** The grace path was exercised by running
a copy with `BOOT_GRACE` raised past the current uptime, because the machine had
been up for twenty minutes and there is no way to be five minutes into a boot
without booting. The reload at 20:53 proved the other half: `bootstrap` fired the
`RunAtLoad` run, it wrote the state file, and — uptime being well past 240 seconds
— it correctly took the *full* path and mailed nothing. **What has not been
observed is the two acting together at a real boot**: `RunAtLoad` firing inside the
grace window, taking the silent rewrite, and the first scheduled run five minutes
later evaluating for real. The prediction is a state mtime within seconds of boot
and no mail, and the next reboot for any other reason will settle it. Until then
this is a fix that has been tested in parts.

**One check of the operator's own turned out to be scoped smaller than it looked.**
`grep "can't assign requested address"` over `com.docker.backend.log` came back
empty, which is true and covers only these two boots — Docker rotated that log at
20:12:32. The original failure's three lines are in
`com.docker.backend.log.20260726-172120.413` at 08:45:29Z, for `:8000`, `:3001`
and `:8002`, which is the same three services the injector above is expected to
break. Reading that grep as "this has never happened" would be the same shape of
error as everything else on this page.

**Six boots of round one, one failed round two, and the two outcomes worth having
are still blank.** What changed is that one of them now has a procedure that can
produce it instead of a lever that cannot, and the other — the container-restore
path — still needs round two rerun, which is the most overdue test on the machine:
the 19:09 boot is the reason that code exists and nothing has exercised it at boot.

### The fifth boot passed and proved nothing, and the two checks written that day could each only say yes

**Round one was run a fourth time and passed.** Plain `sudo reboot` at 19:42:59,
machine back at 19:43:20, hands off. Nine services running with `migrate` at
`Exited (0)`, all six requested bindings equal to actual, all six entrances at
200, Ollama answering on `127.0.0.1:11434` and nothing on the tailnet address.
The reconcile log reads `all expected services running` → `all published bindings
intact`, which is the **first** of the runbook's six outcomes: Docker restored the
stack itself and `tailscaled` won the race, so neither repair path was walked.
**Five boots in, both of the outcomes worth having are still blank.**

It did prove one thing that had no evidence behind it an hour earlier: the
rewritten reconciler is what ran. The fix was committed at 19:41 (`4d8401c`) and
the daemon executes the file in the working tree, so 19:43 is the first boot on
which the named-set precondition, and not the count, decided anything. It decided
correctly and cheaply — `docker daemon responding` at 19:43:39, the container set
already complete, `all expected services running` at 19:43:55, sixteen seconds,
which is three stable samples and no more.

**The margin table gains a fifth row, and the netmap prediction held a second
time — this time stated in advance.**

| boot | `tailscaled` engine start | address usable | Docker's `exposer.Add` | margin |
|---|---|---|---|---|
| 16:45, failed | 16:45:15 | 16:45:32 (+17s) | 16:45:29 | **−3s** |
| 17:21, passed | 17:21:48 | 17:21:48 (+0s) | 17:21:59 | **+11s** |
| 18:08, passed | 18:08:14 | 18:08:23 (+9s) | 18:08:25 | **+2s** |
| 19:09, failed for another reason | 19:09:59 | 19:10:00 (+1s) | *never* | *no race* |
| 19:43, passed | 19:43:28 | 19:43:37 (+9s) | 19:43:39.7 | **+2.7s** |

19:10 loaded the cache and never rewrote it; 19:43 found `netmap cache is not
available` and wrote one at 19:43:38. **The rule that caches do not chain now
rests on two observed load-without-write rather than one**, and the prediction it
makes — the boot after a fast one is a slow one — was written down before this
boot and held. Docker remains the stable side: 11.7 seconds from `tailscaled`
start to the first `exposer.Add`, inside the same 11-to-14 band as the other four.

**The lever this hands the acceptance test is weaker than it read.** The runbook
says to reboot twice and watch the second, because the second has no cache. Both
cache-miss boots on record now pass by roughly two seconds (18:08 +2s, 19:43
+2.7s); the 17-second address that produced the one real failure has not recurred.
It is still the best available bet and it is not a reliable one — a +2s pass is
what "the slow kind" now means.

**The monitor's first real alert cycle is on the record, and it belongs to the
19:10 failure rather than to a drill.** `failing` at 19:14:59, `recovered` at
19:30:03, both mailed. What sat between them was a person: `migrate`'s `StartedAt`
is 19:28:26, which is a hand-run `docker compose up -d` and nothing else. So the
recovery on record is a human's, the reconciler's stack-up path was written after
it, and five boots in that path has still never been walked by a boot. The monitor
is the only part of the chain that has now been exercised end to end by a real
failure rather than by a rehearsal.

**Then both of the day's new checks were tested rather than read, and both had a
defect of the shape this document keeps recording.**

**1. `check-platform-health.sh` counted paused and restarting containers as
running.** It asked `docker compose ps --format '{{.Service}}'`, and `--all` is
documented as adding *stopped* containers — so paused, restarting and created ones
were in the answer all along. Not academic on this host: Docker Desktop's Resource
Saver pauses containers, and the 19:04:18 shutdown path issued an `/unpause`,
which is how we know it had. `postgres`, `redis` and `prometheus` have no probe in
check 6, so check 4 is their only coverage, and paused they would have been silent
in the one place that could have said so. Demonstrated rather than argued: with
`prometheus` paused, the old script exits 0 with the state file still reading `OK`
and sends nothing; the fixed script logs `failing: services,` at 20:01:29 and
mailed at 20:01:32. Unpaused, `recovered: OK` at 20:01:48, mailed at 20:01:51. The
fix is `--services --status running`, which is the question the reconciler was
already asking; the two now agree.

**2. The reconciler's read-back could have no time left to read anything back.**
`DEADLINE` is absolute, and one of the two ways into the repair branch is the
settle loop timing out — the 19:10 boot's exact path. Reached that way, the loop
that verifies `up -d` worked has zero budget, so the first sample, taken in the
gap between `up -d` returning and Compose reporting the container running, prints
`FATAL: still not running` about a stack that is starting. Shown with fault
injection, one lagging sample in a copy of the script: without the fix,
`FATAL: still not running after up -d: grafana` in the *same second* as
`Container rcsl-ai-nexus-grafana-1 Started`, exit 1. With it, one retry and
`stack up: all expected services running`, exit 0. The branch now takes 120
seconds of its own rather than the remainder of a budget that may be spent.

Both fixes are live rather than merely committed, and that was checked rather than
assumed: the plists name the files in the working tree, and the health daemon's
20:03:29 tick ran the fixed script under launchd — `OK`, no mail, nothing in the
log, which is what a quiet tick is supposed to look like.

**The stack-up path itself was walked by hand under normal timing too**, which is
the closest thing to evidence available without a boot that needs it:
`docker compose stop grafana`, then `not running: grafana` →
`docker did not restore the stack; bringing it up` → `stack up: all expected
services running` → `all published bindings intact`, sixteen seconds, exit 0.
**And it restored the binding without recreating anything** — afterwards
`127.0.0.1:3002` requested equals actual and `/login` returns 200. That refines
the recreate rule rather than contradicting it: `up -d` is a no-op against a
container that is already *running* with a stale forwarding table, which is the
case that needs `--force-recreate`; against a *stopped* container it starts it,
and the forward is established then. The two failure modes need the two different
repairs, which is why the script has both.

**What is still unproven, unchanged by all of this.** `OK: all bindings restored`
has never been produced by a boot, and neither has `docker did not restore the
stack; bringing it up`. Both now have hand tests and neither has a boot test, and
a hand test cannot exercise the thing that makes boot hard, which is that nothing
is holding still. One more thing worth knowing before the next run: a hand run of
either script writes to the terminal, not to the log — the redirect lives in the
plist — so `nexus-health.log` legitimately contains no trace of the drills above,
and the state file and the mail are their record.

### Round two, the OS update: nothing brought the containers back, and the reconciler called that a success

**Round two was run — the macOS 26.5.2 update — and it failed.** Legitimately run:
round one had passed three times, which is the gate the runbook sets. Shutdown
19:04:18, machine back at 19:08:46, `macOS 26.5.2` recorded in
`/Library/Receipts/InstallHistory.plist` at 19:09:47, hands off. `docker compose
ps` was empty. Not a dropped port forward this time: no containers at all.

**The two checks round two exists for both passed.** `autoLoginUser` was still
`rcslmac1` and `pmset autorestart` still 1 — the reset that has precedent did not
happen. The failure was somewhere nobody had thought to look, which is the
argument for running the test rather than reasoning about it.

**They were not broken.** All ten are present under `docker compose ps -a`, each
`Exited (0)` from a clean shutdown SIGTERM at 19:04:18, `restart: unless-stopped`
still on every one of them. Docker Desktop simply did not restore them. The engine
reported `running` at 19:10:37 and the backend log has **not one `exposer.Add`**
after it — against a full nine at the same point in the 18:08 boot. Two boots kept
the promise, this one did not. `restart: unless-stopped` is a promise the Docker
daemon makes, and this is the entry that records it is not a property of the
machine.

**Nothing on this host was responsible for the stack being up.** That is the real
finding, and it was true all day without anyone noticing, because Docker had
always happened to do it. The reconciler's repair path fires only for containers
that are *already running* with an empty `NetworkSettings.Ports`; `docker compose
up` appears nowhere in launchd. The whole recovery chain was one layer thinner
than it read.

**And the reconciler reported success while standing in the middle of it.** Its
third precondition waits for the container count to stop changing, and required
`COUNT > 0` before it would settle — so with a count of zero it spun to its
ten-minute deadline, logged `container set settled at 0 running`, swept zero
containers for dropped bindings, found none, and printed `all published bindings
intact; nothing to do` before exiting 0. A script written to repair boot,
reporting a healthy platform at a moment when there was no platform. **This is the
fourth instance of the day's recurring defect and the first one that was inside
the code written to fix a previous instance**: a check whose scope lets it produce
only one answer. Its own header comment warns about exactly this shape, one
precondition earlier.

**The monitor was the only thing in the chain that told the truth.** At 19:14:59
`check-platform-health.sh` flagged all seven — six entrances plus `services` — and
mailed at 19:15:02. It got that right for the reason recorded when it was written:
it compares against a named expected list instead of enumerating what happens to be
running, so a service that is entirely gone still appears. The reconciler had the
opposite property, in the same repository, on the same day.

**The fix is that the reconciler now waits for a named set rather than a count.**
A count cannot tell "not restored yet" from "not coming back"; a list can, because
an absent service is still in the list. Anything missing is brought up with
`docker compose up -d`, the result is read back rather than assumed, and a platform
that is still incomplete now exits non-zero even when every binding that does
exist is correct — otherwise a true statement about part of the platform would go
on standing in for a statement about the platform. Run by hand against the empty
platform it took 28 seconds to bring nine services back with all six entrances at
200, and a second run is a no-op. **That is a hand test, not a boot test.** The
outcome that proves this path is `docker did not restore the stack; bringing it up`
→ `stack up: all expected services running`; runbook §1.1 now lists all six
outcomes and what each one means.

**Why Docker did not restore is not established, and it is left that way on
purpose.** The obvious reading is that an update reboot is not an ordinary reboot:
the two boots that restored were plain reboots, this one carried an OS install
across it, and an update reboot has its own staging rather than being one clean
stop and start. A weaker second reading is in the logs — Docker Desktop appears to
have been in Resource Saver pause when the shutdown began, since the shutdown path
issued `/unpause` at 19:04:18.253 and the containers were SIGTERM'd 0.5 seconds
later. Both are one correlation on one boot, the same size of evidence that
produced the wrong logtail diagnosis recorded below, and neither has a mechanism
anyone here has verified. **Nothing depends on choosing between them**, which is
the point: the repair covers a stack that is not running, whatever stopped it from
being restored. What follows from the update reading is only a test instruction —
§1.1 has to be re-run in full after an update, not just the two settings checks —
and that is worth doing whether or not the reading is right.

**One thing this boot did prove, cheaply.** The netmap-cache model predicted the
next boot would be a fast one, because 18:08:23 wrote the cache. It was:
`Start: loaded netmap from disk cache` at 19:10:00, address up at +1 second, the
widest margin of the four. The prediction has now held once, so the model has two
observations behind it rather than one. It also means the *next* boot is the slow
kind — the one most likely to force `OK: all bindings restored`, the last outcome
still never produced by a boot. The same boot also showed the margin table's
framing is only half right: it measures a race, and a race needs both runners.
The address won by a mile and the platform was dead anyway.

### The third boot: the last unproven link, and the diagnosis that did not survive it

§1.1 was run a third time — `sudo reboot` at 18:07:46, back at 18:08:06, hands
off. **It passed.** The tailnet was up, nine containers running with `migrate` at
`Exited (0)`, all six requested bindings equal actual, all six entrances returning
200, and Ollama answering on `127.0.0.1:11434` with `lsof` confirming it listens
nowhere else. The reconcile log's last line is `all published bindings intact;
nothing to do` — the second outcome for the third boot running, so **the repair
path has still never been walked by a boot.**

**What is new is the one thing the entry below said had no evidence behind it at
all: the health daemon survived a reboot.** It was installed at 17:56, after the
17:21 boot, which made it the only link in the chain never exercised by one.
`nexus-health.state` was rewritten at 18:43:17; launchd loaded the job at 18:08:17
and `18:08:17 + 7×300 = 18:43:17` exactly, so it has been cycling on its interval
since 18:13:17. The boundary worry recorded alongside it turns out not to apply:
launchd cannot load the job before `kern.boottime`, so the first fire is always at
uptime ≥ `BOOT_GRACE` and can never be the one that is skipped. This boot's was at
311 seconds.

**The daemon's own mail path is proven too, and it had not been.** Every mail so
far — the baseline and the three from the `grafana` drill — came from a hand run:
the heartbeat field in the state file read 17:55:30 and the plist was installed at
17:56. Under launchd the environment is a different one (no TTY, no login session,
`PATH` only what the script exports), and an unexercised link of exactly that shape
is what this project keeps being caught by. Forced by ageing the heartbeat field to
an old timestamp so the next tick would owe a heartbeat: the daemon fired at
18:53:18 and logged `mailed heartbeat` at 18:53:20. Two seconds, and
`nexus-health.log` has its first content since it was created.

**The margin table gains a third row, and it is the narrowest pass yet:**

| boot | `tailscaled` engine start | address usable | Docker's `exposer.Add` | margin |
|---|---|---|---|---|
| 16:45, failed | 16:45:15 | 16:45:32 (+17s) | 16:45:29 | **−3s** |
| 17:21, passed | 17:21:48 | 17:21:48 (+0s) | 17:21:59 | **+11s** |
| 18:08, passed | 18:08:14 | 18:08:23 (+9s) | 18:08:25 | **+2s** |

Docker is the stable side: it binds 11 to 14 seconds after `tailscaled` starts, on
all three. The entire variance is how long the address takes to arrive — 0, 9 and
17 seconds. The budget is about eleven seconds.

**The cause recorded for that variance was wrong, and this boot is what shows
it.** The entry below and [deployment.md](./architecture/deployment.md) §9 both
say the failing boot stalled in a logtail bootstrap-DNS retry loop while the
passing one went straight to `Starting`. The 18:08 boot ran the full loop —
twelve DERP hosts for `log.tailscale.com`, then a second round for
`controlplane.tailscale.com` at 18:08:20 — and still won by two seconds. The loop
is not slow: every attempt fails inside the same second with `network is
unreachable` or `no route to host`, which return immediately instead of timing
out. All four boots in the log ran it. It was correlation read as cause, from two
data points.

**The variable is the netmap disk cache.** Every mention of it in
`tailscaled.log`, with nothing omitted:

| time | line | |
|---|---|---|
| 14:12:41 | `writing netmap to disk cache` | |
| 14:42:24 | *(the tailnet ACL is applied — commit `17939ed`)* | |
| 15:53:06 | `netmap cache is not available` | boot |
| 16:45:15 | `netmap cache is not available` | boot, **failed, −3s** |
| 16:45:32 | `writing netmap to disk cache` | |
| 17:21:48 | `Start: loaded netmap from disk cache; 1 peers` | boot, **+11s** |
| 18:08:14 | `netmap cache is not available` | boot, **+2s** |
| 18:08:23 | `writing netmap to disk cache` | |

With the cache the address is up in the same second `tailscaled` starts, because
it does not need control at all — at 17:21:52 it was still reporting `You are
logged out ... failed to resolve controlplane.tailscale.com` with the address
already on `utun0`. Without it, the address waits for control: 9 seconds on this
boot, 17 on the failing one.

**The rule the log supports is that caches do not chain.** The cache is written
when a new netmap arrives from control, and a boot that loads it does not rewrite
it — 17:21 loaded and never wrote, and 18:08 duly found nothing. So a boot that
wins by eleven seconds leaves the next one with nothing and sets up a slow one.
The single apparent exception fits the same rule: 14:12:41 wrote a cache and the
15:53 boot found none, with the tailnet ACL applied at 14:42:24 in between, which
changes the packet filter the netmap carries.

That last step rests on one observed load-without-write, so it is a model rather
than a proven mechanism — but it makes a prediction that costs nothing to check.
18:08:23 wrote a cache, so the **next** boot should be the fast kind and the one
after it slow again. If the margin alternates, this is right.

**It is also the first thing that says how to force the outcome the acceptance
test actually wants.** `OK: all bindings restored` needs a boot that *loses* the
race, and the losing boots are the ones with no cache — which is to say the boot
immediately following one that read the cache. Back-to-back reboots, watching the
second, is a far better bet than rebooting repeatedly and hoping. Recorded in the
runbook §1.1.

Two smaller things. **The §1.1 pass criterion for the state file was written in a
form that cannot be checked after the fact**: it said the mtime should be within
ten minutes of boot, but the file is rewritten every five minutes forever, so at
18:43 the mtime was 18:43 — thirty-five minutes after boot, which reads as a
failure and is not one. What the check is actually asking is whether the mtime is
recent, and it now says so. And `tailscaled.log` is being filled by the ASUS
peer's Dropbox LAN-sync broadcast to port 17500, dropped by the ACL every 31
seconds and logged each time — 389 lines and 111 KB already. The ACL is behaving
correctly; the cost is to the readability of the log that the original fault was
found by reading, so it is on the roadmap rather than ignored.

### Something now watches the state nothing was watching, and what it still cannot see

The entry below ends on the observation that nothing monitored any of this: the
only reason the boot's state was known is that four logs were read by hand. So
`launchd/check-platform-health.sh` and `online.rcsl.health-check.plist`, running
every five minutes and mailing on a change of state.

Seven checks: `TAILNET_IP` readable from `.env`, the address on an interface, the
daemon answering, every expected service running, every requested host binding
actually bound, all six entrances answering over their published ports, and Ollama
answering on loopback while *not* answering on the tailnet address.

**The service check compares against a fixed list rather than enumerating what is
running, and that is the whole design rather than a detail.** Enumerating would
mean a container that is entirely gone never appears in the list being checked, so
the sweep would look at what remained, find it healthy, and report success. That
is the reconciler's missing third precondition again, and `tailscale status
--json` answering "no SSH host keys" to a question it has no field for. Three
times in two days the same shape. The Ollama check is likewise two assertions and
not one: that it answers is availability, that it does not answer on the tailnet
address is §7.1, and the value holding it on loopback lives in a plist that an
upgrade could replace.

Mail goes out on a change only — a failure once, the same failure never again, a
recovery once — and any mail resets the heartbeat clock, so a recovery is not
followed by a redundant "OK" the moment the old timestamp ages out. That is the
shape that teaches people to filter the alerts.

**The daily heartbeat is load-bearing, and it is also the weak point.** A monitor
running on the host it watches can report "up but not serving", which is the
failure that actually happened, and can never report "powered off". A mail
expected daily is what makes silence mean something. But it relies on a person
noticing a mail that did not arrive, and people are far worse at that than at
noticing one that did. The real answer is an external dead-man's switch that
notifies when a ping stops. Not built: it would be the only thing on this machine
that initiates an outbound connection to a third party, which is a decision worth
taking deliberately rather than as a side effect of wanting an alert.

**Verified in that order, against the live stack, rather than assumed.** All seven
pass in the current state. Stopping `grafana` produced `services` and
`probe:grafana` with the detail naming both; an immediate re-run stayed silent;
starting it produced the recovery; the next run was silent again. Then with the
credentials in place the same drill was run for real and three mails were
delivered — the baseline, the failure and the recovery — with the duplicate still
suppressed. Then it was installed as a LaunchDaemon and left alone: the state file
was rewritten at 18:01:38, 300 seconds after the load, by nothing anyone typed.

**The log is events-only, so `did it run` is answered by the state file's mtime.**
Right after installation the log was empty, which is simultaneously "nothing has
gone wrong" and "this never ran" — exactly the ambiguity that made the original
fault invisible, reappearing in the monitor built to catch it. The state file is
rewritten every run precisely so those two readings separate.

**Two things that would have cost an afternoon each.** A Google app password is
displayed as four groups of four and the obvious thing is to paste what is shown;
`tr -d '\r\n'` kept the spaces, and Gmail's answer to a wrong password is a bare
rejection that names no cause. It strips all whitespace now, with a comment saying
why that is right here and wrong in general. And the boot grace and the
`StartInterval` are both 300 seconds, so at boot the first fire lands on the
boundary and the first effective check may be the second one, ten minutes in. That
is deliberate — the first five minutes belong to the reconciler, and alerting
inside them would mail a failure that is about to be repaired — but it means "no
mail eight minutes after a reboot" is not yet evidence of anything.

**The sender is the operator's own Gmail account, which is not what the
documentation recommends.** `secrets/README.md` says to use a dedicated sending
account, because these files are plaintext on a host with FileVault off and that
mailbox is both where every password-reset link arrives and the platform's first
administrator. The deployment went with the personal account anyway, which is a
reasonable call given that an app password cannot log into the web account and can
be revoked on its own. It is recorded as an accepted risk in §15.7 rather than
left as a silent divergence, which is the pattern this file has now warned about
four times.

What is still unproven is that the health daemon survives a reboot. It was
installed after the last one.

### Round one passed, and the margin it passed by turned out to be measurable

§1.1 was re-run against the repaired chain: `sudo reboot` at 17:21:40, hands off,
then the checks. **It passed**, every item. The tailnet was up, Ollama answered on
`127.0.0.1:11434` and nothing on the tailnet address, nine containers were running
with `migrate` at `Exited (0)`, and `/readyz` on the tailnet address returned 200
with all three checks true. The full §7 port table was run rather than just the
one `readyz`: all six bindings requested equal actual.

**Grafana's `127.0.0.1:3002` bound at boot for the first time in the machine's
life.** The backend log shows six clean `exposer.Add` lines at 17:21:59, no
`can't assign requested address` anywhere, and Grafana's destination now
`172.26.0.2:3000` where every previous attempt had been the invalid
`127.0.0.1:0`. The `viz-ingress` change is proven by a boot rather than by hand.

**The reconcile log's last line is `all published bindings intact; nothing to
do`, which is the runbook's second outcome — the one it warns is luck rather than
proof.** The daemon ran 7 seconds into the boot, waited out its three
preconditions, found nothing to repair and exited 0. So the repair path has still
never been walked by a boot, which remains the whole property being claimed.

**How narrowly it passed is measurable, and the two boots bracket it:**

| boot | `tailscaled` engine start | address on `utun0` | Docker's `exposer.Add` | margin |
|---|---|---|---|---|
| 16:45, failed | 16:45:15 | 16:45:32 | 16:45:29 | **−3s** |
| 17:21, passed | 17:21:48 | 17:21:48 | 17:21:59 | **+11s** |

> **Superseded by the 18:08 boot — see the entry at the top of 2026-07-26.** The
> two paragraphs below name the logtail bootstrap-DNS loop as the cause. A third
> boot ran that loop in full and still passed with two seconds to spare; the loop
> completes inside one second on every boot in the log. The actual variable is
> whether the netmap disk cache loads. The timings and the conclusion that the
> reconciler stays load-bearing are unaffected; the mechanism is not.

The seventeen seconds between those two is identifiable rather than random. On the
failing boot `tailscaled` entered a logtail bootstrap-DNS retry loop the moment it
started — `dial "log.tailscale.com:443" failed: no such host`, then bootstrap
attempts against derp2d, derp7, derp4c, derp12c and derp10 in turn — because no
DNS was up yet. `NoState -> Starting` came only after that loop, at 16:45:32, and
the address arrived with it. The second boot went straight to `Starting` and had
the address in the same second.

**The address needs neither the network nor the control plane, which is what makes
the variance startup-side rather than reachability-side.** At 17:21:48 `utun0`
already carried `100.108.250.62`, while at 17:21:52 `tailscaled` was still
reporting `You are logged out ... failed to resolve controlplane.tailscale.com`
and `en1`'s default route did not appear until 17:21:53. The address is restored
from the cached prefs in `/Library/Tailscale`. So what decides the race is only
whether `tailscaled`'s own startup stalls before it runs its state machine.

**That makes the failing boot the ordinary cold-boot path, not an anomaly.** A
cold boot with DNS not yet up is exactly the condition that runs the bootstrap
loop. Nothing in the configuration made this boot skip it, so nothing guarantees
the next one will. The reconciler stays load-bearing, and unproven at boot: round
one has passed, and unattended recovery is an observed property of one boot rather
than a guaranteed one.

Two smaller things. **Nothing monitors any of this.** An outcome of `STILL
UNBOUND`, or a daemon that never ran, would leave the platform down and silent,
which is the property that made the original failure worst — and the only reason
this boot's state is known is that someone sat and read four logs. Prometheus is
already running, so a blackbox probe over the six bindings is the shape of the
fix. And the 17:10 line in the reconcile log that lacks `container set settled` is
not an anomaly: it is the first draft, run by hand before the third precondition
was added, and it is what a check that could only produce one answer looks like in
the log it left behind.

Round two, the 26.5.2 update, is unblocked by the runbook's own gate. Whether to
spend more reboots first, trying to force the `OK: all bindings restored` outcome,
is a separate call — and the odds are not remote, since one of the two boots so
far lost the race.

### The reboot test, which the chain failed in the one way nobody would notice

§1.1 round one was run: `sudo reboot`, hands off, then the checks. **It failed.**
Almost every link held — automatic login, both LaunchDaemons, Docker Desktop's
autostart, nine containers running with `migrate` correctly at `Exited (0)`,
`tailscale serve` config intact, Ollama on `127.0.0.1:11434`. What did not come
back were four of the six published ports. `gateway`, `admin-public` and
`frontend-public` had no host binding at all, so the platform was unreachable
from the tailnet: `curl http://<TAILNET_IP>:8000/readyz` returned `000`.

The cause, from the Docker backend log at 21 seconds after boot:

```
listen tcp4 100.108.250.62:8000: bind: can't assign requested address
```

Docker Desktop restores containers before `tailscaled` has put the address on
`utun0`. The bind fails, **the backend logs one warning and does not retry**, and
because nothing exited, `restart: unless-stopped` never fires. The container runs,
reports healthy, and publishes nothing.

**This is the exact failure the previous entry predicted, and it arrived with the
one property that makes it worst: every casual check says fine.** SSH still
worked, because Tailscale SSH is served by `tailscaled` on the tailnet interface
and never touches a Docker binding. The tailnet admin UI still worked, because
`tailscale serve` forwards to loopback and loopback binds reliably at boot. So
you log in, run `docker compose ps`, see nine containers `Up` and the gateway
marked `healthy`, and conclude the reboot was clean. Only something that actually
crosses the published port finds out. The natural experiment is clean: every
entrance reached through `serve` → loopback survived, 2 for 2; every entrance
binding the tailnet address directly did not, 0 for 4.

**Two proposed fixes were wrong before the third was right, and both were wrong
in the same way — assumed rather than tested.** `docker compose up -d` is a no-op
against a container already running with a matching config; it reported everything
`Running` and restored nothing. `docker compose restart` reuses the container and
leaves the backend's forwarding table alone; grafana came back still unbound. The
forward is created when a container is *created*, so only `--force-recreate`
re-establishes it — verified, and `/readyz` returned 200 immediately after. Had
the reconciler been written to the first design, it would have run every boot,
logged success, and fixed nothing.

So `launchd/reconcile-port-bindings.sh` and its LaunchDaemon. It waits for three
preconditions instead of racing them: the address actually on an interface
(`ifconfig`, not `tailscale status`, because the bind needs the former), a
responsive daemon, and the container count holding steady across two samples ten
seconds apart. The third was missing from the first version and is the same error
again, caught before the test rather than by it — the daemon answers well before
the last container is restored, and at boot they come back one at a time, so
checking on the daemon alone would enumerate only the containers that had already
returned, find those intact, and exit reporting success without ever looking at
the ones still to come. A check whose timing lets it produce only one answer.
Waiting for the count to stop moving avoids picking a fixed delay, which would
have been another guess. It then recreates only the containers whose requested
`PortBindings` have an empty `NetworkSettings.Ports`, which is the precise
signature of the dropped forward. It verifies once and stops. It is deliberately
not `KeepAlive`: it exits non-zero when a binding is beyond repair, and under
`KeepAlive` that would become a container recreated every few seconds forever.
`TAILNET_IP` is read from the same `.env` compose interpolates, so the address it
waits for cannot drift from the address it binds. Written for bash 3.2, which is
what macOS ships — the first draft used `mapfile` and would have failed at boot.

### Grafana's host port had never bound, and the reboot only made it visible

Chasing the above turned up a fourth unbound port that was not a reboot fault at
all. Grafana's `127.0.0.1:3002` had never worked once: the earliest log on the
machine shows `exposer.Add(... 127.0.0.1:3002 -> 127.0.0.1:0)` followed
immediately by `removing`, a forward to an invalid destination.

`metrics-viz` is `internal: true`, and Docker cannot publish a host port into an
internal network — no gateway address means no route from the host, and the
daemon declines with `no suitable container IP found`. That is a *warning*, so
the container starts, reports healthy, and the port is simply absent.
`docker-compose.yml` stated the contradiction in two adjacent comment lines —
"All internal: nothing here is published", then "Grafana is the sole member with
a host port" — and neither the checklist nor anything else ever loaded that port,
so nothing contradicted it.

Publishing requires a non-internal network, and a non-internal network
necessarily grants egress; no Docker bridge configuration gives one without the
other. Grafana now has a dedicated `viz-ingress` for the host port and stays on
`metrics-viz` for the datasource, so Grafana alone pays that cost. The one-line
alternative — dropping `internal` from `metrics-viz` — would have handed the same
egress to Prometheus, which is the single container spanning the gateway and
admin trust tiers and therefore the worst place to put it. Verified after the
change: Grafana reaches `prometheus:9090`, Prometheus answers `Network is
unreachable` to an off-host address, and 3002 returns 200.

**Round one has not been re-run at the time of writing.** The fix is in place and
tested by hand against a live fault, but the property being claimed is that a
*reboot* recovers, and no reboot has happened since the reconciler was installed.
Everything in the previous entry about a chain of individually correct settings not
being evidence applies unchanged, and now with a worked example. Round two, the
26.5.2 update, stays blocked behind a passing round one. *(It was re-run later the
same day and passed without the reconciler having anything to repair; the entry
above records the result and the margin.)*

The runbook gains the check that would have caught this in section 7 — the six
expected bindings, compared as requested-versus-actual rather than read off
`docker compose ps` — and §1.1 now says why `readyz` is the one line in the
acceptance run that cannot be skipped, and why getting in over SSH proves nothing
about whether the platform is serving.

### FileVault deferred, and the headless prerequisites the runbook was missing

The Mac Studio was powered on for the first time, which turned the first-deploy
runbook from a document into something being executed and immediately surfaced a
decision the documents had stated but never sequenced.

`security.md` §9.3 says to keep FileVault enabled and argues it well: physical
theft in a shared facility is worth more than reboot convenience. What it
assumed was the UPS that makes the reboot cost rare, and the UPS is Phase 3 and
does not exist yet. On a headless machine with no UPS, an encrypted disk means
every power cut takes the platform down until someone walks to it, because the
pre-boot unlock happens before there is any network, Tailscale, or SSH. So
FileVault is off for the first deployment, and the UPS is the trigger to turn it
on. Recorded as an accepted risk in §15.6 rather than left as a silent
divergence from §9.3, which still holds as a position.

The decision has a consequence chain worth writing down, because two of its
three links are invisible until something fails to come back after a reboot:
FileVault off is what makes automatic login available, automatic login is what
produces a logged-in desktop session, and that session is what Docker Desktop
needs in order to autostart. Without it the containers' `restart: unless-stopped`
never gets the chance to matter. Enabling FileVault later breaks the first link
and restores the second by a different route, since the pre-boot unlock doubles
as the login.

Working the question through turned up three prerequisites the runbook did not
have, all of which must happen before the monitor is removed rather than after:
remote login, restart-after-power-failure, and startup security. The last one
changes weight rather than appearing from nowhere. §11 already required Full
Security, but with FileVault off it becomes the main control against booting
from external media instead of a second layer behind encryption.

---

## 2026-07-26

### FileVault off, and the unattended-recovery chain that is built but not yet proven

§15.6's sequencing decision was acted on: `sudo fdesetup disable`, and
`fdesetup status` now reports `FileVault is Off`. `supportsauthrestart` returned
true beforehand, so the `authrestart` path exists whenever it goes back on.

The decision was taken with the trade stated rather than assumed. What the
machine now holds unencrypted is the eleven plaintext credential files under
`secrets/`, the TOTP encryption key among them, and whatever research data passes
through the platform; the protection of all of it now rests on Full Security
startup and a locked room, which §15.6 already names as load-bearing rather than
defence in depth.

**Two things in that section's reasoning needed extending, and now say so.** It
treats the UPS as the trigger and the bound on cold boots, which is true for
power cuts and false for everything else that reboots a machine — a kernel panic,
a watchdog reset, a failed update. Each of those lands at the pre-boot unlock
screen just the same, so installing the UPS lowers the frequency of losing
unattended recovery rather than restoring the property. There is no clean way to
have both an encrypted volume and unattended recovery on hardware with no
out-of-band management, and a Mac Studio has none. The second addition is that
this is a constraint on remote operation and not only on data at rest: with
FileVault on, remote access has no fault tolerance, and the one failure that ends
it is the one nothing remote can repair.

**The chain now exists end to end and is not yet proven.** Every link is in
place — the two LaunchDaemons in `/Library/LaunchDaemons` starting without a
login, Docker Desktop's start-at-login, `restart: unless-stopped` on all nine
long-lived services with `migrate` correctly left at `no`, and `pmset autorestart
1` — with automatic login the last piece. What has not happened is a reboot. A
chain of individually correct settings is not evidence, and the failure mode is
silent: the service is simply gone, with nothing to say which link broke.

So the runbook gains §1.1, the one test in it that must be run with a person at
the machine. Two rounds, deliberately separate: a clean reboot first, because it
has one variable, and the pending macOS 26.5.2 update second, because combining
them makes a failure unattributable. The post-update check includes re-reading
`autoLoginUser` and `pmset autorestart`, since macOS updates have been known to
reset exactly those, and they are two links of this chain. Until both rounds
pass, remote system updates should not be attempted: an update that stops at an
interactive screen cannot be cleared remotely.

The runbook also now states the general rule the whole day kept running into.
The dividing line for what is safe to do remotely is whether the action can
affect the next boot. Development, platform administration, container
operations, ACL and membership changes: all safe. FileVault, automatic login,
major upgrades, anything touching `tailscaled`'s ability to start: one-way doors
on a machine with no remote console.

### Remote access, and a diagnostic that invented the wrong conclusion

The machine is headless, so it needs a way in. It is Tailscale SSH, gated by the
`ssh` block that was already sitting in §3.4, with `action: check` forcing
re-authentication every twelve hours. macOS Remote Login is off: `tailscaled`
serves SSH on the Tailscale interface only, so §11's "listening on the Tailscale
interface only" is satisfied by not running a second SSH server rather than by
editing `sshd_config`, and there is no password or key that can leak. Remote
Login had been enabled during the attempt and was binding every interface,
including the LAN, accepting passwords — the exact shape §11 exists to prevent.
Nothing answers on `127.0.0.1:22` now, which is the useful check precisely
because Tailscale SSH does not bind loopback.

**The detour is worth recording, because the wrong turn was mine and it was a
measurement error.** Concluding that Tailscale SSH does not run on macOS, I read
`tailscale status --json` for SSH host keys and found none. That field does not
exist in the JSON, so the probe returned "absent" no matter what the truth was,
and the conclusion followed confidently from a check that could only ever produce
one answer. Acting on it, the `ssh` block was removed from the ACL — which was
the only thing authorising SSH — and the next attempt failed with `tailnet policy
does not permit you to SSH to this node`. The banner is precise and says exactly
what happened; the earlier reasoning had made it look like confirmation of the
platform theory instead. `RunSSH` in `tailscale debug prefs` is the field that
answers the original question, and it had been `true` throughout.

The generalisable part: a probe that cannot distinguish "absent" from "I asked
the wrong question" is worse than no probe, because it converts uncertainty into
false confidence. That is the same failure mode as the day's other six, arriving
from the diagnostic side rather than the configuration side.

**Two properties came out of it that are now in the documents.** Tailscale SSH
needs both halves — port 22 in `acls` to carry the connection and the `ssh` block
to authorise the session — and the two failures look nothing alike: without the
port the connection never arrives, without the block `tailscaled` answers and
refuses. The runbook now carries that split as a table, plus the log line that
tells them apart (`handling conn` in `tailscaled.log` means the connection
reached the server, so the problem is authorisation, not networking).

And a tagged node has no user identity, which reaches past SSH: `tailscale whois`
for `tag:ai-server` lists tags and no user, so `tailscale serve` has no
`Tailscale-User-Login` to inject for a connection from the server itself. The
tailnet management entrance cannot be exercised from the machine it runs on. That
is a property of tagging rather than a misconfiguration, and it is now stated in
both §3.4 and the runbook's bootstrap step, because the obvious first test is the
one that cannot work.

### Inference served end to end, and a model that could never leave its initial state

`POST /v1/chat/completions` now works on the target hardware, streaming and not,
from socket through key verification, quota, the trusted-proxy check, the country
filter, the routing policy, the GPU, SSE framing, and back out to a usage record.
That is Phase 1's stated goal observed rather than argued.

Non-streaming returned in 0.51s with `finish_reason=stop`. Streaming produced
twelve frames in the OpenAI envelope — a role frame, content deltas, a terminal
frame carrying `finish_reason`, then `[DONE]` — and reassembled correctly.
`usage_records` holds one row per successful request, stamped with the default
tenant; the two requests that were refused earlier in the path recorded nothing,
which is right, because neither reached the use case. The gateway's `/metrics`
reports `nexus_inference_requests_total 2` and `nexus_inference_tokens_total 33`,
matching the two completions exactly. The admin chat panel had produced two
further usage rows and no gateway metrics, which is also right: it is served by
the admin entrance, not the gateway.

Two things about the request shape are worth writing down, because both looked
like faults for a minute. The OpenAI `model` field carries the **capability**,
not a model alias — `RouteChatRequest` resolves a policy by capability and the
policy chooses the model, so `"model": "qwen7b"` is refused with
`no_available_model` while `"model": "chat"` succeeds. And in production the
gateway refuses anything that did not arrive through the proxy, so testing before
nginx exists means presenting `X-Nexus-Proxy` and an `X-Forwarded-For`. Both
refusals were the design working; neither is documented anywhere a caller would
look, which the API reference should fix when it exists.

**Before any of that, a registered model could not be downloaded at all.**
`model-table.tsx` offered `Unload` when the state was `loaded` and `Load` in every
other case — including `not_downloaded`, where the use case's precondition
guarantees a 409. A freshly registered model was therefore a dead end: the only
button available was the one that could not work. The backend endpoint, the
`startDownload` client, the `useStartDownload` hook, the `useDownloadJob` poller
and the `DownloadProgress` component all existed; the hook and the component were
never referenced from anywhere. The whole download UI was built and never wired
in, which is why `ROADMAP.md` could carry `features/models: download progress via
useDownloadJob` as done, and why this file could claim the models table polls that
endpoint. It does not; nothing did.

The actions now mirror the use cases' own preconditions, so a button that is
present is a button that can succeed: `Download` unless the model is loaded,
`Load` only from `downloaded`, `Unload` only from `loaded`. The table also owns
the job now, because `useDownloadJob` stops polling at a terminal state without
telling anyone, so the row would otherwise sit at `downloading` until a reload.

A measurement worth keeping: the loaded model is 5.7 GB resident against 4.7 GB of
weights, where the same model measured 6.6 GB this morning under a hand-started
`ollama serve`. The difference is `OLLAMA_KV_CACHE_TYPE=q8_0`, which the committed
plist carries and an ad-hoc run does not — so the KV cache the memory budget's
headroom has to absorb is about 1.0 GB here, not 1.9 GB.

### The stack is up on the Mac Studio, and the frontend could not reach its backend

First full `docker compose up` on the target hardware. `migrate` exited 0 having
logged `database roles provisioned: nexus_gateway(gateway), nexus_admin(admin)`,
all ten containers came up, and the gateway's `/readyz` returned all three checks
true — including `runtime`, which means the container reached the native Ollama
through `host.docker.internal` for real rather than in a test.

**The account split is now enforced by the deployed database, on this machine.**
`pg_stat_activity` shows the gateway connected as `nexus_gateway` and the two
admin entrances as `nexus_admin`. As `nexus_gateway`: `SELECT` on `api_keys` and
`routing_policies` succeeds, `INSERT` into `usage_records` succeeds, and `INSERT`
into `api_keys`, `users` and `audit_log` are each refused with `permission
denied`. That is the §6 property proven where it finally matters. The published
ports match §3.2 exactly: gateway and admin-public on the tailnet address only,
admin-tailnet on loopback only, nothing on `0.0.0.0`.

**Then the management UI turned out to be unreachable, for a reason that
`docker inspect` actively hides.** Every `/admin/*` call from either frontend
failed, the log reading `Failed to proxy http://localhost:8001/admin/me
ECONNREFUSED`, while the container's environment plainly carried
`ADMIN_API_URL=http://admin-tailnet:8001`. The rewrite lived in
`next.config.js`, and `output: 'standalone'` serialises the resolved config into
`.next/required-server-files.json` at build time — so `process.env.ADMIN_API_URL`
was read during `pnpm build`, where the Dockerfile never sets it, and the
`?? 'http://localhost:8001'` fallback was compiled into the image. Confirmed by
grepping the shipped bundle: it contains `http://localhost:8001` and nothing
else. The runtime variable was correct, present, and ignored.

The fallback is what made it silent. Without it the build would have failed and
the defect would have been caught on the machine that built the image; with it,
the image builds clean, starts clean, reports healthy, and fails only when a
human tries to sign in.

The fix is `frontend/src/middleware.ts`, which resolves the destination per
request. That was chosen over build args because the two entrances need
different destinations while sharing one image, which is the arrangement
`docker-compose.yml` documents; baking would have forced two images. The env is
read inside the handler rather than at module scope, since module-scope access
is the shape a bundler can constant-fold — the same failure in a different
place. An unset variable now logs and returns 500 instead of defaulting.
Verified: both entrances now reach their own admin API (401 and 400 from the
backends respectively, not 500), with no ECONNREFUSED.

**A tagged server cannot sign in to its own tailnet entrance.** Testing the
bootstrap from the machine itself returns 401, and correctly so: `tag:ai-server`
was applied earlier today, `tailscale whois` for the node lists Tags and no User,
and the `Tailscale-User-Login` header `tailscale serve` injects is derived from
the connecting node's owner. A tagged node has none. The runbook said to use
"your device" without saying why the obvious first attempt cannot work, so it now
says so, and gives the loopback curl that tests the backend directly.

That curl also demonstrates §5.1 rather than describing it: adding the header by
hand to a request against `127.0.0.1:8001` authenticates as an administrator,
which is exactly why that entrance binds loopback and why a shared Docker network
with the gateway was a defect worth the network split. It also bootstrapped the
first administrator as a side effect — `users` now holds
`leolove3very@gmail.com` as `admin` in the `default` tenant, and `audit_log`
holds one `bootstrap.first_admin | success` row, which is §12's requirement
observed on a live deployment rather than in a test.

### The tailnet ACL, which the runbook never told anyone to apply

`ROADMAP.md` has carried a checked box reading "Tailscale ACL including
`tag:ntnu-proxy`, so members cannot bypass the proxy" since the architecture was
written. It described a template in `security.md` §3.4. There was no tailnet to
apply it to until today, and the runbook — which is the document that exists so
nothing gets skipped — never mentions applying it or tagging the server at all.

Following the runbook exactly therefore ends here: `sudo tailscale up` joins the
tailnet under the default policy, which for a new tailnet is
`{"src": ["*"], "dst": ["*"], "ip": ["*"]}`. Every rule in §3.4 hangs off
`tag:ai-server`, and a device that joined without `--advertise-tags` carries no
tag, so none of them matches. The failure mode is not that nothing works; it is
that everything is reachable. Any device subsequently added to the tailnet could
open `100.x.y.z:8000` or `:8002` directly and bypass every control the proxy
applies — the exact sentence §3.4 opens with, latent for as long as the tailnet
had one member and live the moment it had two.

There is a sharper consequence downstream. §8 asks the NTNU proxy administrator
to join under `tag:ntnu-proxy`, but a tag cannot be applied unless `tagOwners`
already names it. Without the ACL step, that request fails on the other person's
machine, for a reason nothing in the runbook explains.

**Applied, and then pinned.** The policy is now live on the real tailnet, and the
machine carries `tag:ai-server` with key expiry disabled — Tailscale's 180-day
default would otherwise have dropped a 24/7 server off the tailnet half a year
in. The part worth keeping is the `tests` block added to §3.4: Tailscale runs it
on every policy save and rejects a policy that fails one, so "a human member
cannot reach the data-plane ports" and "the proxy cannot reach the management
endpoints" are now assertions rather than prose. Both pass. The runbook gained
the two missing steps in the order they have to happen, since tagging before the
ACL exists cannot work.

The pattern is the same one this file recorded twice already today, and the
header warns about generally: a control that was designed, written down, marked
done, and never actually in force. The account-split test asserted nothing; the
Ollama loopback bind would not have survived a reboot; the pnpm allowlist was
inert; this ACL was a file nobody had applied. None of them looked wrong.

### GPU inference, verified at last, and two runbook steps that were quietly wrong

Runbook §3 and §4 are done, and the claim the whole machine exists for is no
longer a claim: `ollama ps` reports **100% GPU** for `qwen2.5:7b`, generating at
91.7 tok/s with prompt evaluation at 180 tok/s, at the 32768 context that
`MAX_CONTEXT_LENGTH` already configures. A container reaches it through
`host.docker.internal` and gets a completion back, so §0.1's whole bet — runtimes
native, containers calling out to them — is now measured rather than reasoned.

**A number the memory budget will want.** The model's weights are 4.7 GB and its
resident size while loaded is 6.6 GB; the difference is the KV cache at 32k
context. `MemoryBudgetService` counts only `resource_profile.memory_gb`, which is
the weights, and leaves the rest to the 20% headroom — so the headroom is
carrying about 40% of weight size per loaded model at this context on this
architecture. That ratio is not linear in model size and must not be extrapolated
to the 51.2 GB the budget currently permits, but it is the first real measurement
of the quantity §4.3 has been guessing at, and it is what the deferred
`MetricsPort` ingestion should be calibrated against.

**The runbook's Ollama service step was a silent security failure.** It said to
run `launchctl setenv OLLAMA_HOST 127.0.0.1` and then `brew services start
ollama`. `launchctl setenv` writes to the boot session domain and does not
survive a reboot, and Homebrew's plist carries no `OLLAMA_HOST` of its own — so
the first restart would drop Ollama back to its `0.0.0.0:11434` default and
publish inference to the LAN, with nothing to indicate it had happened. The bind
required by §7.1 has to survive a reboot without help, so the value now lives in
a plist committed at `launchd/online.rcsl.ollama.plist`. Two further corrections
came with it: a LaunchDaemon rather than Homebrew's LaunchAgent, because an agent
waits for a login that a headless machine after a power cut will not get; and an
explicit `UserName`, because a daemon defaults to root and would look for models
in `/var/root/.ollama` and find none. §7.1(d)'s dedicated service account is the
later hardening step, and that key is where it will land.

**§4 had a smaller version of the same gap.** It opens with `sudo tailscale up`,
but `brew install tailscale` starts no daemon, so the step fails with `failed to
connect to local Tailscale service`. `sudo brew services start tailscale` comes
first, and the `sudo` is load-bearing for the same reason it is on Ollama: it
makes the difference between a system daemon that boots and a user agent that
waits for a login.

The machine is on the tailnet at `100.108.250.62`, MagicDNS
`rcslmac1demac-studio.tail68e30b.ts.net`, and `.env` now carries that address and
the bootstrap login with no placeholders left. `tailscale serve` waits for the
frontend to exist. The only thing still blocking a first `docker compose up` is
the GeoLite2 database, which `ENV=production` with a non-empty
`ALLOWED_COUNTRIES` refuses to start without.

### The Mac Studio exists, and a test that had stopped testing anything

The deployment host is real now, and the first thing it did was falsify a claim
this file has been making for a week.

The machine is the one [ARCHITECTURE.md](./ARCHITECTURE.md) §0.2 describes: M4
Max, 64 GB unified memory, macOS 26.5. It arrived bare, so this started at
runbook §2 — Homebrew, then git, tailscale, ollama, uv, node and pnpm, then
Docker Desktop. Compose parses against the real `.env` and the real file
secrets, and the §1/§3.2 network invariant holds here as it did on the dev
machine: the intersection of the gateway's networks with each admin entrance's
is empty. `host.docker.internal` resolves from inside a container, which is the
whole of §0.1's bet that runtimes stay native.

**`test_db_role_grants.py` had been failing since 968b2ee, in the way that
hides itself.** The integration suite runs only when `TEST_DATABASE_URL` is
set, and nothing had set it since multi-tenancy landed, so the first full run
here was the first run since. The test opens with the gateway's one legitimate
write — an INSERT into `usage_records` — before asserting the six writes it
must be denied. Multi-tenancy made `usage_records.tenant_id` NOT NULL and did
not update that INSERT, so the test aborted on a constraint violation at its
first statement and **none of the six denials was ever asserted**. The same
staleness sat in the admin positive control on `users`.

The property itself is sound: with `tenant_id` supplied, all six denials pass
and the server refuses the gateway account an INSERT into `api_keys`, `users`,
`routing_policies` and `audit_log`. So this was a test defect, not a security
defect. What it cost was the evidence — and this file and `ROADMAP.md` have
both been citing that evidence by name. The multi-tenancy entry below calls the
account split "undisturbed" and reasons its way there correctly, but reasoning
is the thing the test existed to replace. This is the drift the header of this
file warns about, caught by the first machine that actually ran the suite.

**Two toolchain divergences, from the same first run.** `uv` had no
`.python-version` to read and `requires-python` says only `>=3.12`, so it built
the environment on 3.14 while `backend/Dockerfile` ships `python:3.12-slim`:
local verification and the deployed artifact were different interpreters. The
pin is now `backend/.python-version` and the suite was re-run on 3.12.
Separately, ruff 0.16.0 flags S608 on the tenant backfill's `UPDATE {table}`,
where the only interpolation is a table name from a literal tuple in the same
module and the value is bound. Suppressed inline with its reason rather than by
widening the existing per-file ignore, so it stays greppable.

Verified on this machine: 359 tests pass on Python 3.12 against a real Postgres
17 (299 unit, 60 integration — the integration half for the first time on Apple
Silicon), ruff and mypy clean over 127 files, `docker compose config` resolving
the real secrets. What still waits is everything needing the stack actually up:
GPU inference, MLX, `tailscale serve`, nginx, the GeoLite2 database, and the
live free-memory figure the memory budget is still standing in for.

**An operational note that is not a code change.** The host is configured as a
personal computer rather than a server: FileVault on, which makes auto-login
unavailable and stops an unattended reboot at the unlock screen; `pmset
autorestart` off, so it does not come back after a power cut; and Docker
Desktop's VM was sized at 8 GB against a memory budget whose 20% headroom is
meant to cover the OS, the containers *and* inference working memory. The VM is
now 4 GB. The rest is §15.6's sequencing decision and waits on the UPS.

---

## 2026-07-25

### Logs UI and usage charts, and a chart library chosen by not choosing one (Phase 2)

Two frontend Phase 2 items, both needing a backend read path first. Neither the
audit log nor the usage table had one: auditing was write-only (its adapter
commits each row in its own transaction so a failed request still leaves a
trail), and usage had only the dashboard's 24-hour totals. So the work is a
read path on each, then the screens.

**The audit read is an ordinary scoped query, kept away from the writer.** A new
`AuditEntry` entity and `PostgresAuditLogRepository` read the append-only table on
the request session, tenant-scoped by the same `_scope` helper every other read
uses, with `ReadAuditLog` behind `logs:read` (a scope that already existed in the
enum, unused until now). The write side stays on `AuditPort` and its independent
transaction: reading must not borrow that machinery. The page is bounded (a
default 50, a hard 200) because an operator UI never needs the whole table and an
unbounded limit is a memory lever on a table that only grows. The frontend
`features/logs` is server-paged rather than a client-side table over one fetch,
for the same reason, with action and outcome filters that reset to the first page
so an offset cannot point past a smaller filtered set.

**Usage analytics reads the accounting table, which is not what Grafana shows.**
The distinction from the observability commit earlier today matters: Prometheus
reports live operational state to an operator over Grafana; this reads
`usage_records`, per tenant, for the management UI. Different audience, data, and
access path. A `date_trunc` aggregation (`bucketed_usage`) groups by time bucket
and capability in one query, and `ReadUsageAnalytics` (behind `usage:read_all`,
the scope the dashboard totals already use) folds the rows into per-bucket totals
and per-capability series. The window is a small closed set (24h, 7d, 30d) that
fixes the bucket granularity with it, so the query's cardinality is bounded and
the range picker maps to exactly three shapes; time comes from an injected clock
so the windowing is testable.

**The chart-library question, which the codebase had deliberately deferred, is
settled: no library.** The `MetricChart` placeholder had recorded the open
decision (Tremor had shifted to copy-in source with the §10 supply-chain caveat;
Recharts was the fallback but a real dependency with a React 19 version
constraint). The data these screens show is simple magnitude-over-time, so the
charts are inline SVG instead: a component that draws lines and an area with axes
and a hover tooltip, and the pure geometry (scales, path building, nice-max
rounding) in `chart-geometry.ts` where it is unit-tested with no DOM. Series
colours read the theme's computed `--chart-1..5` ramp through `currentColor`, so
they follow light and dark without a second palette. The trade is that axes and
the tooltip are ours to maintain; that is acceptable while the charts stay simple
time series, and a richer visualisation would be the point to revisit it. One
series renders as a filled area, several as plain lines with a legend.

The dashboard's two chart placeholders now carry real 24-hour data from the same
endpoint, and its note no longer promises Phase 2: it points at usage records for
counts and at Grafana for the live operational metrics.

Verified: 6 new backend unit tests (the two use cases' authorization, the page
clamp, and the fold from buckets into totals and per-capability series) and 3
integration tests against real Postgres (the audit read's tenant isolation and
newest-first ordering, and that `date_trunc` buckets by hour and capability while
excluding another tenant's rows); the full backend suite passes, mypy and ruff
are clean. On the frontend, 9 new tests (the chart geometry and the two response
schemas), `pnpm test`, `eslint`, and `next build` with the `/logs` and `/usage`
routes generating. One small structural consequence worth noting: extending
`UsageRepositoryPort` with `bucketed_usage` meant the `MeteredUsageRepository`
decorator from this morning had to delegate it too, which mypy caught rather than
leaving for runtime.

### Observability: the emission side, and the word "metrics" pulled apart (Phase 2)

The Phase 2 item read "MetricsPort with Prometheus and Grafana; live metrics
replace the static memory budget," and the first useful thing was noticing it
conflates two different things the codebase already keeps apart. There is a
`MetricsPort` in the domain, and it is the *ingestion* side: `free_memory_gb`, a
live hardware figure the memory budget would consult instead of static capacity.
And there is the thing every deployment actually wants first, the *emission*
side: the process exposing what it is doing so Prometheus can scrape it. This
change ships emission in full. The ingestion half stays deferred on purpose,
because a real free-memory number for the node exists only on the Mac Studio, and
`security.md` §4.3 already says the budget must not wait on metrics: so the budget
stays static and authoritative until the figure is real, which is the
conservative reading of that rule rather than a gap.

**The instruments are derived from what the code already produces, so the
delicate paths are untouched.** HTTP series (request count, duration, in-flight)
come from one pure-ASGI middleware. Pure ASGI rather than `BaseHTTPMiddleware`
because the gateway's reason for being is streaming, and `BaseHTTPMiddleware`
returns once the response object exists, which for an SSE stream is before a
single token has gone out: timing and the in-flight gauge would measure
time-to-first-byte, not the duration a request actually occupied a slot. Wrapping
`send` and recording when the response truly finishes fixes both. Inference series
(tokens, completion outcome, duration by capability and model) come from a
`MeteredUsageRepository` that wraps the usage repository and reads the same
`UsageRecord` the streaming use case already writes in its `finally` — so
`RouteChatRequest`, the most carefully ordered file in the tree, gains observation
without a line of instrumentation in it. The concurrency-slot gauge is read from
the live limiter at scrape time rather than tracked through the request path, so
it cannot drift out of step with the semaphore it reports.

**The route label is a template, never the raw path.** An id in a URL would make
each request its own time series, and a port scanner hammering 404s would turn
unbounded cardinality into a memory problem. The middleware reconstructs the
matched template from the router's path params and collapses anything unmatched to
a single `__unmatched__` label. No label carries a caller identity, tenant, or
key, for the same reason and because the exposition body is an information
disclosure if it ever leaks.

**Which is why /metrics is guarded, not merely placed on an internal network.**
The gateway carries `/metrics` on the same ASGI app that faces the proxy, so
network placement alone would rest on the operator's nginx being precise forever.
The endpoint requires a bearer token from a file secret — the same shared-secret
pattern the trusted-proxy check already uses — and returns 404, not 401, without
it, so a caller does not even learn it exists. On the admin entrances `/metrics`
is exempted from the geo/proxy perimeter (like health) so Prometheus can scrape
over the internal network; the token is the actual control there. Placeholder
tokens are refused in production exactly like the other secrets, but only when
metrics are enabled, so a deployment that runs no Prometheus is not forced to
invent one.

**Scraping does not reopen the gateway/admin isolation.** Prometheus scrapes all
three apps, so it sits on both a gateway-side scrape network and an admin-side
one, but the gateway and the admin entrances still share no network with each
other, which is the §1/§3.2 invariant (`docker compose config` confirms the
intersection is empty). The only node on both is Prometheus, and unlike Postgres
and Redis — also dual-homed but never initiating — Prometheus does initiate. What
makes it safe is that it is a scraper, not a forwarding proxy: it issues only the
fixed `GET /metrics` requests in its config, so a compromised gateway cannot use
it to reach an admin entrance. Grafana is on the Prometheus network only, binds
loopback, and is reached over `tailscale serve`; Prometheus publishes no port.
Grafana's default `admin`/`admin` is replaced from a file secret, with anonymous
access and self-registration off, which is the §6 requirement that had been
sitting unactioned.

Verified: 18 new unit tests (the token guard returning 404 on all three apps, the
disabled-endpoint case, a served request counted under its template, the slot
ceiling reported, a scanner's paths collapsing to `__unmatched__`, the label
reconstruction, and the metered repository emitting from a record while still
persisting it); the full unit suite at 290 passing; ruff and mypy clean; and
`docker compose config` renders with the network invariant intact. What waits for
the Mac Studio is what always does: real scrape traffic, and the ingestion figure
that would let the budget go live. The two dependent Phase 2 items, the logs UI
and in-app usage charts, are unstarted; Grafana covers the metrics view for now.

### mypy made honest, and put where it cannot drift again

Running `mypy app` over the whole package, which this log had repeatedly called
clean, turned up 24 errors. Two things had been hiding them.

There was no automation. pre-commit ran gitleaks and ruff but never mypy, and
there is no CI, so "mypy clean" was an impression from running it by hand on
whichever module was just written, never the whole package at once.

And the config's relaxation was inert. A block declared `strict = false` for
`app.adapters.*`, on the reasoning that adapters wrap third-party libraries with
incomplete stubs. But mypy silently ignores `strict` in a per-module override:
it is a global-only meta-flag, so the adapters were strict-checked the entire
time, and the comment describing them as relaxed was describing something that
was not happening.

The one error worth calling a defect rather than noise was a contract lie. Both
runtime adapters typed `generate` and `pull` as returning `AsyncIterator`, while
`ModelRuntimePort` promises `AsyncGenerator`. `AsyncIterator` is the wider type
and does not guarantee `aclose()`, which is the exact promise the port's own
docstring spends a paragraph on, because that promise is the streaming contract:
without it a disconnected client leaves the runtime generating and the slot held.
The behaviour was correct (an `async def` with `yield` is an async generator), but
the annotation was weaker than the code, and it was the mismatch mypy flagged at
`di.py` as the adapters not satisfying the port. Aligning the annotations closed
that and the port-conformance errors together.

The rest were ordinary: a missing `target: Model` and three unannotated function
parameters, a response-variable that needed widening to `Response`, and a
`type: ignore` that no longer suppressed anything. Genuine third-party stub gaps
(SQLAlchemy typing async `execute` as `Result`, which lacks `rowcount`; redis
returning `str` under `decode_responses=True` but typed `bytes | str | None`;
huggingface_hub not exporting two error classes) are pinned with targeted casts
and `type: ignore` at the call site, where they are visible and greppable, rather
than a blanket relaxation that would hide real errors alongside them. The inert
override is gone, replaced by a comment recording why it never worked.

To stop the drift recurring, a local pre-commit hook now runs
`uv run --directory backend mypy app` on any change under `backend/app`. Local
rather than mirrors-mypy so it type-checks against the project's real resolved
dependencies instead of a hand-maintained second copy, and whole-package because
mypy's cross-module inference is what makes it accurate.

One change surfaced a latent issue. Giving `chat_completions` a return annotation
(`ChatCompletionResponse | StreamingResponse`) made FastAPI try to build a
response model from a union containing a `Response`, which it cannot; the fix is
the documented `response_model=None`. It was caught immediately by the unit tests
that load the gateway app, not left for deploy, which is the payoff of the
annotation existing at all. Verified: `mypy app` reports no issues over 118 files,
ruff is clean, and 272 unit tests pass.

### The last resource guardrail: a wall-clock generation deadline

Auditing ROADMAP §120 against the code found the item mislabelled rather than
missing. Of the four guardrails it lists, three were already built and wired:
the concurrency cap (`SemaphoreConcurrencyLimiter`, held for the whole generator
in `RouteChatRequest`), the `max_tokens` output ceiling (min of the caller's
request and our cap, pushed to Ollama's `num_predict` so the model stops at the
source), and cancel on disconnect (`aclosing` throughout, so the adapter closes
its upstream HTTP request). A fourth, the per-request context bound, was wired
too, closing the `max_context_length` setting that an earlier review had flagged
as configured and read by nothing. Only "timeout" was partial: the adapter has a
per-read HTTP timeout, but nothing bounded the total wall-clock time of a
generation.

That gap is narrow but real. The token ceiling bounds a stream producing at a
healthy pace, and the per-read timeout bounds a stalled one (no bytes for the
interval). The uncovered case is a stream that keeps producing slowly enough to
stay under the read timeout yet never reaches the token cap, which on unified
memory near swap can hold one of only two concurrency slots for hours. With no
edge protection that is a genuine, if edge, denial-of-service lever.

So `RouteChatRequest._generate` now checks a wall-clock deadline in the yield
loop and cuts the stream with `finish_reason=length`, the same honest signal the
token-ceiling truncation already uses, so an OpenAI client is not told the model
finished. The deadline is `generation_deadline_seconds` (default 600, zero or
negative disables it, matching the heartbeat convention). Elapsed time comes from
an injected `monotonic` callable rather than the wall-clock `Clock`, for two
reasons: an NTP step must not move a live generation's deadline, and the seam
lets the deadline be tested without any real waiting. Two unit tests drive it: a
slow runtime that advances the injected clock ten seconds per token trips a 25s
deadline after three tokens and releases its slot, and a zero deadline falls back
to the token ceiling. 272 unit tests pass; ruff is clean and mypy shows no new
errors over the pre-existing baseline.

What waits for the Mac Studio is the same boundary inference has always had: the
guardrail's arithmetic and the truncation contract are exercised now against an
injected clock, but a real slow generation on the GPU is only observable there.
The pre-launch checklist item in security.md §14 that says to verify the
guardrails in practice still stands.

### Multi-tenancy, the isolation boundary made real (Phase 2)

The third Phase 2 item, and the most invasive: the platform was single tenant and
said so, and this makes the boundary exist. Every `users`, `api_keys`,
`usage_records` and `audit_log` row now carries a `tenant_id`, a migration
backfilled the existing rows into one default tenant, and the tenant-scoped
repositories filter every read and stamp every write by it.

**The filter lives in the adapter and is taken from the actor, never the caller,
which is the whole of section 7.3.** A tenant-scoped repository is constructed
with a tenant id, and the di builder takes that id from the authenticated actor
(`users.tenant_id` on the admin entrances, `api_keys.tenant_id` on the gateway),
so a use case receives an already-scoped repository and cannot read another
tenant's rows or forget to say which tenant it means. The use cases themselves
barely changed, which is the payoff: the boundary is structural, not something
each handler remembers. A scoped read adds `WHERE tenant_id = :t`; a scoped write
stamps the repository's tenant onto the row regardless of what the entity carried;
and the targeted updates (revoke, disable, edit) carry the tenant into their
`WHERE`, so a scoped operation cannot touch another tenant's row even by its id.
The integration test proves all of this against a real Postgres, which the unit
fakes cannot, because they have no filter to enforce.

**A few paths are deliberately unscoped, and each resolves a principal before any
tenant is known.** Authentication looks a user up by a globally-unique login, the
session resolver looks one up by id, the gateway looks a key up by its handle, and
bootstrap counts every user platform-wide. Reading exactly the one row a unique
handle names is not a cross-tenant enumeration, and the tenant is then read from
that row. These use an explicit `.unscoped()` repository, so the choice is visible
and greppable rather than a forgotten default.

**A review of these three Phase 2 commits caught where the scoping went one step
too far.** The invite flow's duplicate-login check had been left on the
tenant-scoped repository, but a login is a platform-global namespace: `users.login`
is globally unique, so a login already taken in another tenant would slip past a
scoped check and fail at the unique constraint as a bare 500 rather than the clean
409 the check exists to give. `get_by_login` is now never tenant-scoped, for the
same reason authentication resolves it globally: it answers only "does this login
exist anywhere", and the row it returns carries its own tenant. The review's other
findings were hygiene rather than logic: a docstring displaced onto the wrong
field, a stray UTF-8 BOM and mangled em-dashes that a scripted `.unscoped()` edit
had left in four integration test files, an unhandled promise rejection in the
tenant-create dialog, and a duplicated onboarding-link builder now shared between
the users and tenants routers.

**Shared infrastructure stays platform-global.** `models`, `nodes` and
`routing_policies` are the compute the tenants share (one loaded model serves
everyone), so they carry no tenant and are managed by any admin. Tenants
themselves are platform-global too: managing them is an admin operation, not
tenant data.

**Minimal but usable tenant management.** `ManageTenants` creates a tenant and,
in the same call, mints its first administrator's invitation into that new tenant
(a tenant with no admin cannot be populated), and lists tenants. The ordinary user
invite lands in the inviting admin's own tenant, stamped by the scoped repository.
There is no platform-super-admin versus tenant-admin split yet: admins are
platform-trusted, which suits a single research centre, and the stricter hierarchy
can follow if a genuinely external tenant appears. The knowledge base, the main
tenant-scoped consumer, is not built yet; it plugs into this boundary when it is.

One structural change made it clean: `current_actor` and `current_session` moved
from the identity middleware into `di.py`, so the scoped-repository builders can
depend on the actor without the middleware and the composition root importing each
other in a cycle. The middleware re-exports both, so routers and the entrance apps
are untouched.

Verified: the migration round-trips (it seeds and backfills the default tenant, so
the column is NOT NULL with no data-migration window); the account split is
undisturbed (the gateway's schema-wide SELECT already covers the new table, and it
still has no write on `api_keys`, `users` or `tenants`); 270 unit tests pass, with
four new for `ManageTenants` and a five-case integration test pinning the isolation
property against real Postgres; ruff and mypy are clean on the new code; and the
frontend gained a `features/tenants` screen (list plus a create dialog that shows
the first admin's one-time link) through `tsc`, `eslint` and `next build`.

### Node management, and the SSRF guard that had to ship with it (Phase 2)

The second Phase 2 item, and the one the security document had been holding a
rule over: a node write endpoint may exist only if the SSRF guard ships with it,
because a node's `address` is a value the platform makes outbound requests to,
and an attacker who can register `169.254.169.254` or `127.0.0.1` has turned node
management into internal probing (§7.2). Until now the rule was satisfied by the
absence of a write path: the single node was seeded from configuration and no
endpoint accepted an address. This change adds the write path and the guard
together.

**The guard is the core, and it validates on the way in, not only on the way
out.** `adapters/http/egress_guard.py` resolves an address and requires every
result inside the tailnet range (`100.64.0.0/10` and the Tailscale IPv6 ULA).
One range is the whole rule: loopback, link-local, the RFC 1918 LAN, and the
cloud metadata endpoint are all outside it, so none has to be enumerated. A
literal IP is checked without a DNS lookup, which also means the value stored is
the value connected to; a hostname is resolved and rejected if any answer falls
outside the tailnet, so a name that resolves partly off-net cannot pass on the
strength of one good record. The check runs at every node write, so an address
that could never be reached safely is refused before it is stored rather than
surfacing later as a failed probe. It reaches the use case through
`EgressGuardPort`, not a direct import, the same discipline that keeps
model-reference validation off the application layer.

**Status stopped being an assumption.** Phase 1 wrote every node `online` at
provision and never looked again, which made a routing requirement of
`node_status: [online]` inert, since it always held. A `NodeHealthPort` now
observes status by probing the runtimes a node declares (online when all answer,
degraded when some do, offline when none does or none can be probed), and a
heartbeat in the admin application runs it on an interval. So a policy that
demands an online node actually stops routing to one whose runtime has gone away.
The heartbeat runs in the admin app rather than the gateway because the §6
least-privilege split lets the gateway write only `usage_records`, never
`nodes`; both admin entrances run it, which is why the write is a targeted,
idempotent `set_status` and why a status is written only when it changed. The
loop sleeps before its first sweep, so the many tests that open and close the
admin lifespan cancel it before it ever touches the database. Single-node scope
is stated plainly in the adapter: the runtime adapters point at the configured
host runtime, so the probe is accurate for the one node they can reach and a
second node will need per-node runtime endpoints, deferred with multi-node.

**Deletion is guarded too.** `models.node_id` is a foreign key, so deleting a
node with models attached would fail as an IntegrityError at flush, which in
FastAPI is after the response has gone and has nowhere to report. The use case
refuses it first, naming the models, and the same shape gives a duplicate node
name a clean 409 instead of a unique-violation 500, matching how `ManageModels`
already reports a taken alias. Registration and removal are audited, as §12
requires.

`GET /nodes` moved from the models router to a new `routers/nodes.py` carrying
the full lifecycle: the read the model form needs plus register, edit, delete,
and an explicit health check for the UI's refresh action. The frontend gained a
`features/nodes` management screen (table with live status, a create/edit form
whose address field is validated server-side, delete, and check-now) and a nav
entry. The stale "node management is Phase 1 read-only" comments across the
models feature were corrected rather than left to mislead.

Verified: 27 new backend tests (the egress guard against loopback, LAN, metadata
and rebinding; `ManageNodes` for the guard running before a store, the
attached-models delete refusal, status as the probe's observation; the heartbeat
writing only changed statuses), the full unit suite at 266 passing, ruff and
mypy clean on the new code, and the frontend through `tsc`, `eslint`, and
`next build` with the `/nodes` route generating. Real probing of a runtime still
waits for the Mac Studio, the same boundary inference has; the guard, the write
rules, and the heartbeat's change-detection are exercised now.

### The second runtime adapter, which is the real test of the layering (Phase 2)

The first Phase 2 item, and the one worth doing first because it answers a
question the rest of Phase 2 assumes: did the hexagonal layering actually buy
what it was chosen for. The stated pass criterion was that adding a runtime
touches no use case and no interface. It held. The diff is one adapter file
(`adapters/runtime/mlx_adapter.py`), its per-runtime reference grammar
(`adapters/runtime/hf_validation.py`), and three wiring points: one entry in
`build_runtimes`, one setting, one Compose mount. `application/use_cases` and
`interfaces` are untouched, and the domain is too, because `RuntimeKind.MLX`
already existed. `route_chat_request` resolves the adapter from the model's
`runtime` field through the same dict it always did.

The value of the exercise was less the wiring than the three places MLX is
genuinely unlike Ollama, each of which the port absorbed without bending, but
only after a real decision.

**MLX has no download-with-progress endpoint, and its download lands somewhere
Ollama's never had to.** Ollama's daemon pulls on the host and streams NDJSON
progress back, so the adapter only relays. MLX models are HuggingFace snapshots
and `mlx_lm.server` downloads them lazily with no progress stream. So `pull`
here does the download itself, via `huggingface_hub` in a worker thread, and
reports real byte progress by polling the cache while it runs. The subtlety that
forced a decision: a download run inside the container would land in the
container filesystem, which the host-native server cannot read. The bytes have
to reach the host cache. So HF_HOME is a bind mount onto the host's HuggingFace
cache, and this is the one place in the deployment a container writes to a host
path. That does not contradict the section 0.1 rule that runtimes are not
containers: the rule is about GPU and compute, and a snapshot download is file
I/O whose only constraint is where the bytes end up.

**`mlx_lm.server` has no unload, so `unload` refuses rather than lying.**
Reporting success would move the registry to DOWNLOADED while the weights are
still resident on the host, and the memory budget would then stop counting a
model that is still occupying memory, admitting a later load that should be
refused. That is precisely the unified-memory over-commit the section 4.3 budget
exists to prevent. The adapter raises `ModelStateConflictError`, and
`ManageModels.unload` already does the right thing with it: the model is left
LOADED, which is the truthful state, and the operator gets a 409 that says the
runtime cannot evict. A silent no-op would have been the dangerous option, not
the convenient one.

**The token count is only authoritative at the end**, in the terminal usage
frame, exactly like Ollama's `eval_count`. Chunks are counted one apiece as they
stream so a disconnect still bills what was produced, and the final frame emits
only the difference rather than the whole figure, which would double-count.

The reference grammar is per-adapter, as `ModelRuntimePort.validate_ref` intends:
a HuggingFace repository id, not Ollama's `namespace/name:tag`. It rejects `..`
and anything that is not a plain repo id at the boundary, because the value
reaches `snapshot_download(repo_id=...)` and a repo id carrying path traversal
is the section 7.1 concern in a different runtime's clothing.

Verified with 12 port-conformance tests against a stubbed transport and stubbed
download seams, no MLX and no GPU in the loop: the OpenAI SSE stream maps to
`CompletionChunk` and reconciles the token total, the upstream request is closed
on client disconnect (the guarantee the streaming contract rests on), a bad
reference is rejected before any network call, a stream that ends without a
terminal frame raises rather than reporting a clean stop, `unload` refuses
without touching the network, and `pull` climbs monotonically from starting to
success. The full unit suite is 237 passing; ruff and mypy are clean.
`huggingface_hub` is imported lazily inside the download seams only, so the
inference path neither pays its import cost nor depends on the library being
present, and the mypy override mirrors the existing zxcvbn one.

What waits for the Mac Studio is real MLX inference and a real download, which
need Apple Silicon and cannot run on the Windows dev machine, the same boundary
Ollama inference has always had. The architecture claim itself does not wait for
that: it is the zero use-case, zero-interface diff plus the port-conformance
suite, and both are done now.

### A production smoke test on the dev machine, which moved the deploy risk down

Ran the whole stack once on Windows under `ENV=production` with generated
(non-placeholder) file secrets, which exercises the Compose wiring the account
split had only been structurally checked against. It held: `migrate` exited 0
having run the migrations and logged `database roles provisioned:
nexus_gateway(gateway), nexus_admin(admin)`, so `db_roles` created both roles
from the mounted URL secrets and applied their grants in the real flow. All
eight containers came up; postgres, redis and the gateway reported healthy, and
`/readyz` returned 200 on the gateway and both admin entrances. `pg_stat_activity`
showed the gateway connected as `nexus_gateway`, not the owner. And the boundary
is enforced by the deployed database, not just by the earlier unit and
integration tests: as `nexus_gateway`, `SELECT api_keys` and an `INSERT` into
`usage_records` both succeed, while `INSERT INTO api_keys` is refused with
`permission denied for table api_keys`.

What this does not cover, and still waits for the Mac Studio: the country filter
(run with `ALLOWED_COUNTRIES` empty, since there is no GeoLite2 database here),
GPU inference, `tailscale serve`, and nginx. The production config validators,
the role provisioning, the per-account connections, and the grant enforcement
are no longer first-run risks.

### A first-deploy runbook, and the GeoLite2 mount it turned up

Compiling the Mac Studio pre-deploy checklist ([runbooks/first-deploy.md](./runbooks/first-deploy.md))
surfaced a blocker: the Compose file mounted no `/data` into the backend
services, but `build_geo_filter` refuses to start in production when
`ALLOWED_COUNTRIES` is set and the GeoLite2 database is missing. So the stack as
written would have failed to boot on the first real deploy. The `x-backend`
anchor now bind-mounts `./data` read-only, and the runbook step is to drop
`GeoLite2-Country.mmdb` there. The runbook is written for someone who has not
used macOS: first boot, Homebrew, Docker Desktop, native Ollama bound to
loopback, Tailscale and `tailscale serve`, the secrets, and the §14 checks that
must be tested rather than assumed.

### The database account split, and secrets moved to file mounts

The last functional-to-operational Phase 1 item, and the deeper half of the
defence the network split (§15.5) only started. Until now every backend service
connected as one account that owns the schema, so a compromised gateway that
could not reach the admin socket could still write `api_keys` and mint itself a
key. Now there are three Postgres accounts: the gateway reads every table and
writes only `usage_records`; the two admin entrances share an account with full
DML and no DDL; the owner holds DDL and is used only by `migrate`.

The roles are provisioned in code (`infrastructure/db_roles.py`), run by the
`migrate` job after the schema exists. Three decisions carried it.

The grants are **declarative, not additive**: the gateway's table privileges
are revoked and re-granted on every deploy, so its writable set is always
exactly `GATEWAY_WRITABLE_TABLES` regardless of what a previous run left, and a
table added by a later migration is regranted without anyone editing SQL. The
one writable table is named in code, where it is under review, rather than in a
deployment file.

The account **name is taken from each service's own connection URL**, so the
URL secret is the single source of truth for both the name and the password;
this module never invents a name the deployment did not commit to. `migrate`
connects as the owner and reads the gateway and admin URLs to create those two
roles.

And the SQL is **built as text with hand-quoted identifiers and literals**,
because `GRANT`, `CREATE ROLE`, and a role password are DDL that no driver
parameterises. The quoting helpers are the standard minimal escapers, safe
under `standard_conforming_strings`; role names are additionally constrained to
a strict pattern because a name is an identifier we control. `exec_driver_sql`
rather than `text()` runs them, so a colon in a generated password is not read
as a bind parameter. Ten unit tests pin the security property directly: the
gateway is granted no write anywhere but `usage_records`.

Alongside it, secrets moved from `env_file` to Docker **file mounts**. This was
forced by the split as much as chosen: an environment variable outranks a file
secret in pydantic-settings, so a value left in `.env` would silently override
the mounted one. `.env` now carries only non-secret configuration; every
credential is a file under `./secrets` (git-ignored, with `.example` templates
and a README), mounted at `/run/secrets` and read through `secrets_dir`. Each
service mounts only what its role needs, except that the four crypto secrets go
to `migrate` too, because it calls `get_settings()` and production refuses the
placeholders. Postgres reads its password through `POSTGRES_PASSWORD_FILE`;
redis, which has no such convention, reads the file in its command.

**What is verified, and what waits for the deploy.** The security property
itself is now proven against a live Postgres 17: an integration test
(`tests/integration/test_db_role_grants.py`) provisions the two roles the way
`migrate` does and asserts the server refuses the gateway account an INSERT into
`api_keys`, `users`, `routing_policies` and `audit_log`, while keeping its reads
and its `usage_records` write, with the admin account as the positive control.
`docker compose config` resolves the secret mounts as intended and the unit
suite passes. What still waits for the Mac Studio is the full compose wiring end
to end: `migrate` creating the roles from the mounted URL secrets, and each
service connecting as its own account rather than the single-account
`AUTH_MODE=dev` default the Windows machine uses.

### A routing policy editor, so the one thing that makes the gateway serve is no longer curl-only

The routing policy API was complete and audited but had no screen, so the
single thing that decides what the gateway serves for a capability was
configured by hand. `features/routing-policies` now carries a table (one row
per capability, candidates summarised highest-priority-first to match how the
gateway evaluates) and a candidate editor: a `useFieldArray` over the candidate
list, each with a model alias, a priority, and the structured requirement as
checkbox groups over node status and model state plus an optional free-memory
floor.

Three decisions worth the note. The requirement stays a closed set of
structured fields rather than an expression box, exactly as the domain demands
(ARCHITECTURE.md section 2.4): the same reason the backend refuses one is the
reason the form does not offer one. Creating a policy is only offered for
capabilities that do not already have one, because a save is a full replacement
keyed by capability (`PUT`) and a "create" over an existing capability would
silently overwrite it. And the memory floor is backed by a text input where a
blank field means "no floor" and becomes null, kept out of a plain
`z.coerce.number()` because coercing an empty string yields zero, which would
read as a real 0 GB requirement rather than the absence of one; the schema test
pins that.

The response schemas parse against the same enums the models feature uses, so a
node status or model state the frontend does not know surfaces as a parse
failure rather than a candidate that silently never matches. Verified through
`tsc`, `eslint`, `next build` (the `/routing-policies` route generates), and ten
new schema tests.

### A frontend test runner, on the units where a defect is a security defect

The one Phase 1 gap most worth closing first, because the type checker had been
the only gate and two of the three defects it let through were security
defects. Vitest with jsdom, and 44 tests over the pure logic the adversarial
review had already found holes in: `safe-redirect` (the backslash open-redirect
that survives a prefix check), the chat SSE schema and reader (the OpenAI
envelope that an earlier flat schema silently stripped to nothing, plus the
error, malformed, truncation and abort frames), `api-client` (the CSRF header
attached only on mutations and only when the cookie is present, the 401 that
becomes an `UnauthorizedError` and an event, and the absence of any
`Authorization` header), and the password schema's length-and-strength
threshold.

Two decisions worth the note. The `@/` alias is resolved in `vitest.config.ts`
directly rather than through a tsconfig-reading plugin, so the test setup does
not depend on how that plugin parses config. And the jsdom environment runs on
`https://localhost/` because the CSRF cookie carries the `__Host-` prefix,
which jsdom's cookie jar correctly refuses to store over http, so a test on
http would have been asserting against a control that the browser also drops.
The test files are excluded from `tsconfig.json` so `next build` does not try
to type-check them.

What is not covered: nothing renders a component or drives a browser yet. The
sign-in and enrolment screens, which are the surface where a defect is a
security defect, are still only reachable through their schemas and hooks in
these tests. Playwright is the deferred increment, recorded in `ROADMAP.md`
Phase 3.

### Closed the network exposure the review left standing

The sharpest finding, recorded as accepted risk §15.5, is now fixed rather than
carried. The gateway and the tailnet admin entrance shared the `app` Compose
network, and the tailnet entrance trusts `Tailscale-User-Login` outright, so a
compromised gateway could reach `admin-tailnet:8001` by service name and forge
an administrator. Socket binding, the design's stated isolation, protects the
host-published port but not the Docker service name.

The single `app` network is split so the gateway shares none with either admin
entrance. The data plane gets `gateway-data` (internal, for postgres and redis)
and `gateway-egress` (for the host runtime); the control plane gets `admin-data`
and a per-entrance control network carrying the frontend and its admin API.
postgres and redis are the only members of both database segments, which is
safe because they accept connections and never open one — a shared datastore is
not a shared path. The same split also stops the internet-facing public frontend
from reaching the tailnet entrance.

The invariant is not a comment but something `docker compose config` can be
asked: the intersection of the gateway's networks with each admin entrance's is
empty. What remains open is the deeper §6 defence, per-service database
credentials, so a compromised gateway cannot read or write the control plane's
tables; the forged-header path specifically is gone.

### Five adversarial reviews, and the twenty-eight defects they found

The admin API was attacked by five independent reviews, each on one surface:
authentication and sessions, authorization and data exposure, persistence and
concurrency, the model lifecycle and jobs, and the frontend/backend contract.
Their findings were verified before acting, and the verification mattered:
several passed against the in-memory fakes while being wrong in Postgres, and
one review's headline claim needed a real database to confirm.

Most of these were introduced by the two admin-API commits above. The fixes
are in four commits after this one; what follows is why they existed.

**Four defects made the system unusable.** Every admin call 404'd, because the
Next.js rewrite keeps the `/admin` prefix and the routers mounted at the root;
nothing caught it because every test called the ASGI app directly, so they
exercised handlers and never the contract. No API key could be issued, because
the expiry field is an `<input type="date">` that sends a naive datetime and
comparing it to an aware `now` raised `TypeError`, a bare 500. Both create
paths destroyed their one-time secret, returning the unsaved entity whose
`created_at` is null, which the frontend's parse rejects after the row exists,
taking the plaintext key and the invitation link with it. And a compromised
gateway could authenticate as an administrator: it shared the `app` Docker
network with `admin-tailnet`, which binds `0.0.0.0` and trusts
`Tailscale-User-Login` outright, so §5.1's "isolation by socket binding" held
for the host-published port but not the bridge. (Closed since, by the network
split described in the entry above.) That last one is the sharpest lesson:
making the tailnet entrance a full API is what opened it, and it was invisible
while the entrance mounted only health.

**Controls the design claimed and the code did not deliver.** The login
throttle refused on a per-account count alone, which is the hard lockout §5.3
forbids because it is a denial-of-service lever against a named person, and a
successful login cleared the per-address counter so one valid account could
reset it. A `user` could mint an unmetered gateway key, because the gateway
reads `rate_limit_rpm <= 0` as no limit and quota zero as no quota, and expiry
had no upper bound. The country filter was absent from the public admin
entrance while four places said it was present, one of them a router comment.
CSRF was absent from the tailnet entrance on the false premise that it has no
ambient credential, when `tailscale serve` attaches the identity header to any
request a hostile page can provoke.

**State and data corruption.** A failed load wrote `error` and then raised,
and the raise rolled the write back, so a half-resident model read as
`downloaded` and the budget under-counted it. The three transient states were
permanent dead ends after a crash, escapable only by SQL. The download task
held one transaction open for the whole multi-hour pull. Two full-row `save`
calls could revert a concurrent revoke or disable. Each of these had a passing
test that used an in-memory fake with no transaction and no row lock, which is
why the new coverage runs against real Postgres.

The lower-severity findings — a `user` role wider than §5.2, a challenge that
outlived a disable, two CSRF paths that 500'd, `GET /api-keys` loading full
user entities, a double SSE terminal frame — are in the fourth fix commit.

**What was checked and found sound, so it is worth recording as tested:**
session fixation and the watermark invalidation, TOTP replay across every skew
case, the bootstrap atomicity, enumeration resistance, the model-reference
grammar (`fullmatch` closes the trailing-newline hole and the registry
allowlist rejects `hf.co.evil.com`), the streaming slot released within a
millisecond of disconnect, and the migrations round-tripping with zero ORM
drift.

**Residual items, accepted or deferred rather than fixed:**

- **Commit-after-response.** FastAPI commits the request transaction after the
  response is sent, so a create returns `201` with the body before the INSERT
  is attempted; a constraint violation then has nowhere to report. The
  narrow trigger is a TOCTOU on a uniqueness check under concurrent identical
  creates. Structural to how the yield-dependency session works; not changed.
- **A model stuck in a transient state by a bare container crash** (not a
  `compose` restart) is reconciled only at the next deploy, because
  provisioning runs in the `migrate` service. `restart: unless-stopped`
  brings the container back without re-running it.
- **The concurrent-load budget race** is narrowed, not closed: `LOADING` is
  now committed independently and counted, so the window is milliseconds
  rather than the whole load, but two loads landing in that window can still
  both pass. A node advisory lock would close it and is deferred.
- **`session_signing_key`** is enforced as a production secret and read by
  nothing: sessions are opaque Redis ids by design. Left in place, noted here.

### The rest of the admin API

Models and their lifecycle, downloads as background jobs, routing policies,
API keys, the remainder of `/users`, the dashboard, and `/admin/chat`. An
integration test now walks Phase 1's stated goal in one sequence: register a
model, bind a routing policy to it, issue a key, and read the dashboard back.

**A gap that only appeared once the endpoints existed: nothing could create a
node.** Models attach to one, and `security.md` §7.2 says a node write
endpoint must ship with the SSRF guard, because a node record is an address
the platform will then make outbound requests to. So a fresh deployment could
register nothing at all. Phase 1 is single-node by definition, so the node is
named in configuration and written at admin start instead. That keeps the rule
intact rather than working around it: nothing accepts an address from a
caller, and the write endpoint still waits for the guard.

**`last_used_at` is derived, not stored.** The frontend wanted the column, and
maintaining one would mean the gateway writing to `api_keys` on every request
— which is precisely what the least-privilege split in §6 exists to prevent.
The same fact is already in `usage_records`, written by the account that
should write it and indexed on `(api_key_id, at)`, so it is one aggregate at
list time. The dashboard's 24-hour figures come from there too; the frontend
schema had them as Phase 2, but Phase 2 is live metrics from Prometheus, and
request and token counts have been in the database since Phase 1.

**Model reference validation moved onto the port.** Registering a model needed
the same check the Ollama adapter already performs, and importing it into the
application layer would have been the layering violation fixed a day earlier.
Putting it on `ModelRuntimePort` is the better answer anyway: what counts as a
reference differs by runtime. Ollama takes `namespace/name:tag` from a small
set of registries, MLX takes a HuggingFace repository id, vLLM will take a
path. A shared helper would have to be the union of all of them, which is no
grammar at all.

**Where the state machine can lie.** Most of the model tests exist for
failures that leave a plausible-looking row. A failed load writes `error`, not
`loaded`. A failed *unload* writes `loaded`, not `error`, because as far as
anyone knows the weights are still resident and the memory budget has to keep
counting them. A crashed download writes `error` in a `finally`, since a row
stuck in `downloading` is one no later operation will touch and nothing sweeps
up. Deleting a model whose alias a routing policy names is refused: no foreign
key enforces that binding, and without the check inference starts answering
"no available model" with nothing in the registry to explain why.

The download job runs detached, in its own transaction, because the request's
session is closed the moment the response is sent. It does not survive a
restart, which is accepted rather than solved: a durable queue is a second
piece of infrastructure to run for one operation, and keeping progress in the
cache means an interrupted pull is visibly stuck rather than silently gone.
The set of strong task references in `infrastructure/jobs.py` is not
decoration — `asyncio` holds only weak ones, and a task nobody keeps can be
collected mid-await with nothing logged.

Two smaller things. SSE framing moved into one module, so the gateway and the
chat panel cannot drift into two envelope shapes; that drift is exactly what
made the chat panel display nothing the first time. And the runtime port now
declares `AsyncGenerator` rather than `AsyncIterator`, because every consumer
wraps it in `aclosing()` and only the former promises `aclose()` — the
promise the whole streaming contract rests on.

---

## 2026-07-24

### Admin authentication, end to end

Both admin entrances now resolve an identity, and a fresh deployment can get
from an empty database to a signed-in user on the public entrance. That path
is covered by an integration test which runs bootstrap, invitation, TOTP
enrolment, login and sign-out against a real Postgres, because none of the
unit tests would notice a composition root that wired the wrong adapter in.

Built: argon2id, pyotp, Fernet encryption for the TOTP secret, token issuing
and recovery codes, the audit adapter, sessions on the existing `CachePort`,
CSRF, the two identity resolvers, and the use cases behind them.

**Authentication was built before the CRUD, and the ordering paid off twice.**
Both times the shape of the existing schema rejected the first design rather
than accepting it quietly.

**The check constraint refused the obvious place to keep a pending TOTP
secret.** Enrolment spans two calls: one renders the QR, the other verifies a
code from the authenticator that scanned it, so the secret has to survive
between them. Writing it to the user row looked right, since
`can_use_public_entrance` already requires a password as well and a row with
only a secret authenticates nothing. But `users` carries
`(password_hash IS NULL) = (totp_secret IS NULL)`, added in the last review,
and it rejected the write. The constraint was right: a half-finished enrolment
is not an account. The candidate now waits in the cache for minutes, which is
better on its own terms. Abandoning a re-enrolment leaves the working
authenticator untouched, an unproved secret exists nowhere for 72 hours, and
the unauthenticated `begin` endpoint no longer writes to `users` at all.

**Creating an account and its invitation in one transaction violated a foreign
key.** The ORM models declare foreign key columns but no `relationship()`, so
SQLAlchemy's unit of work has no dependency graph to order a flush by, and
with `autoflush=False` — which production uses deliberately — the invitation
INSERT was emitted before the user it referenced. `PostgresUserRepository.save`
now flushes. This is the mirror of the defect found last time, where the tests
relied on an implicit flush that production does not do; here the production
code relied on an ordering nothing guarantees, and only a real database could
say so.

**A test-only hang that is worth recording.** The first end-to-end test opened
both entrances as concurrent `TestClient`s. It hung forever. `init_engine`
holds one engine per process and asyncpg connections belong to the event loop
that created them, so the second client's requests waited on futures from the
first client's loop. Production never meets this, because the entrances are
separate containers. The test opens them one after the other.

**And a latent ordering bug in the suite itself.** A unit test configures an
unreachable database to prove `/readyz` can fail, and cleared the `lru_cache`
on `get_settings` going in but not coming out. `alembic/env.py` overwrites
`sqlalchemy.url` with `get_settings().database_url`, so every integration test
that ran afterwards migrated against a dead host. It had never shown up
because the integration suite is skipped unless `TEST_DATABASE_URL` is set,
and the two had not been run together.

**Three decisions worth their reasoning.**

`PasswordHasherPort` is async, and the adapter runs argon2 in a bounded thread
pool. A hash occupies a core for tens of milliseconds, and login is
unauthenticated and behind no WAF, so a synchronous port would hand an
attacker a cheap way to stall every request in the process, including the ones
that would have rate limited them. anyio's default 40 threads at 64 MiB each
would then trade a CPU stall for an out-of-memory kill, hence the semaphore.

Audit rows are written in their own transaction. `session_scope` rolls back on
any exception, so an audit row sharing the request's session disappears
exactly when the request failed, and failures are what an audit log is for.
The cost is the mirror case, an audited action that later rolls back, which is
what `outcome` is for.

The entrances choose their identity resolver by dependency override, and the
placeholder raises. A branch on `settings.auth_mode` would have been a string
comparison deciding a trust model, which is the thing section 5.1 says the
isolation must not rest on. An application that installs neither resolver now
fails on its first authenticated request rather than defaulting to anything.

Two things changed outside the plan. `users` gained a `created_at` column,
because the frontend user schema already displayed one and no column existed.
And the invitation QR endpoint takes the token on its URL: the recipient is
not signed in, so there is no session to identify the enrolment from, and an
`<img>` cannot carry a request body.

Still absent, and the reason the frontend is not yet usable end to end: models,
routing policies, API keys, jobs, dashboard, `/admin/chat`, and the rest of
`/users`.

### Theme and progress tracking

Deep blue theme, a busy indicator, and this file.

The palette is computed rather than chosen by eye: `#1e40af` measures 8.72:1
against white, which clears AAA for body text, and dark mode moves up the ramp
to `#60a5fa` at 7.79:1 against the dark background rather than reusing a value
that would be unreadable there. Charts use a sequential ramp, because the
dashboard shows magnitude over time and a categorical palette would imply
categories that do not exist.

Two decorative elements adapted from Uiverse.io, credited in
[`ATTRIBUTIONS.md`](../ATTRIBUTIONS.md). Only two, and only decorative: that
collection is thousands of pieces by as many authors with no shared design
language and, being showcases, generally no focus or disabled states. Useful
for a spinner, wrong for anything a user operates.

**No logo.** A constructed wordmark and an N-as-routing-graph icon were drawn
and then discarded; the identity will come from elsewhere. There is no icon
asset in the repository, so the browser tab falls back to the framework
default until one is supplied.

### Everything the adversarial review found, fixed

Five independent reviews were run against the codebase, each attacking a
different surface. Their findings were verified before acting, which mattered:
the loudest one was wrong.

**The claim that did not survive verification.** A review argued that streaming
requests never commit their usage record, because FastAPI closes a
yield-dependency before a streaming response is produced. The reasoning was
sound and the conclusion was false for the installed version. An empirical test
showed both paths persisting. A second review found why: FastAPI 0.139 keeps
the dependency scope open until the response is sent, but the declared floor
was `>=0.115`, and versions in between do not. So the real defect was a
dependency range, not a design fault, and the fix was a pin plus the
regression test that had been missing.

**Live security holes, since the gateway is the only exposed surface.**
Scopes were computed and then never consulted, so any valid key could consume
the hardware regardless of what it was issued for. The per-key quota was dead
in two independent ways. `rate_limit_rpm` was stored end to end and enforced
nowhere. `TAILNET_IP` had no required-variable guard, so an unset value made
Compose bind the gateway to every interface, which was verified before and
after.

**The one worth remembering.** The quota read `tokens_used_today` off the key
repository through a `getattr` fallback that returned zero when the method was
missing. The method lives on a different class. The fallback had been written
to make the check stubbable in tests, and it was precisely what hid the
miswiring: the only object with that method was the test double, so the tests
passed while production never checked a quota at all. A defensive default
around a wiring mistake is worse than the crash it prevents.

**Frontend.** The chat could never display a reply: the frame schema described
a flat shape while the backend sends the OpenAI envelope, and zod strips
unknown keys rather than rejecting them, so every real frame parsed
successfully into an empty object. The login page was an open redirect via
`/\evil.example`, which the URL parser normalises to a second slash. One-time
secrets could be destroyed with the Escape key. `Me` carried no `id`, so two
callers substituted `login` and one of them left an admin able to delete
themselves.

**Persistence.** Single use was not single use: the atomic guard was correct
and its rowcount was discarded, so two requests reaching the same invitation
both believed they had claimed it. TOTP replay prevention compared a value
read earlier and wrote it back, which two concurrent requests both pass.
Invariants that existed only as Python properties are now check constraints.

**Documentation.** Several controls were described in the present tense and did
not exist. The worst was in `db.py`, whose docstring asserted that each service
connects with its own least-privilege account and that "the grants do the
enforcing", while Compose gives every service one account that owns the schema.
That is the same mistake `security.md` had already warned about for tenant
isolation: a claimed boundary stops people looking for the risk.

**Two defects were found by the new tests rather than by review.** Splitting a
use case into two generators reintroduced a missing `aclosing` one layer up,
caught immediately by the disconnect test. And aligning the test sessions with
production `autoflush=False` produced foreign key violations, because the tests
had been relying on an implicit flush that production does not do.

### Guardrails that were configured but never read

Four settings existed in `config.py`, in `.env.example` and in the
documentation, and were read by nothing.

`/readyz` returned hardcoded booleans, so it could never produce a 503, and its
test asserted only that the status was one of 200 or 503 and therefore passed
vacuously. Anything gating a rollout on readiness was gating on a constant. It
now probes the database, cache and runtime concurrently, each bounded by a
timeout, because a probe that hangs is worse than one that fails: the
orchestrator waits instead of acting.

The country filter did not exist at all. `geoip2` was a dependency,
`allowed_countries` and `geoip_db_path` were read by nothing, and
`CountryNotAllowedError` was defined and never raised, which is worse than
absence because a defined error implies a control. It now refuses to start in
production when its database file is missing, rather than silently serving
every country.

`max_context_length` was likewise inert, so a prompt of any size was accepted.
And `/docs` was gated on `not is_production`, but `ENV` defaults to development
and `.env.example` ships it, so a deployment that filled in its secrets and
left the top of the file alone was publishing its full internal schema.
Exposure is now an explicit opt-in, so forgetting fails closed.

### Phase 1 backend, end to end

Postgres repositories and the first migration, the Ollama adapter, and the
chat path wired from socket to SSE frames.

The runtime is stubbed in the end-to-end tests and nowhere else. Inference
needs a GPU and can only be verified on the Mac Studio; everything between the
socket and the port boundary is real, including the routing policy read from
the database.

Three defects found while building: `.env.example` shipped a `DATABASE_URL`
whose password did not match `POSTGRES_PASSWORD`, so a fresh checkout could not
connect; `alembic/script.py.mako` was missing, so revision generation failed
outright; and `key_id` was an independent random value that appeared nowhere in
the token, leaving verification no way to find the row short of scanning every
key.

### Scaffold

Backend hexagonal skeleton, Next.js management UI, Compose topology, AGPL-3.0.

The hardware constraint that shaped the deployment: **model runtimes cannot run
in Docker on macOS**, because containers there have no GPU access. A
containerised Ollama would be CPU-only and MLX would not run at all, which
defeats the point of the machine. Runtimes are native under launchd; containers
reach them through `host.docker.internal`.

Three image-build defects that only appeared by actually running
`docker compose build`, all of which `docker compose config` validated happily:
four services declaring `build:` while sharing one tag raced to write it,
`package.json` had no `packageManager` for corepack to activate, and neither
build context had a `.dockerignore`, so the host's `node_modules` and a Windows
x86 `.venv` were being copied into Linux images.

### Licence: AGPL-3.0

Chosen to match the sibling project, Smart-MultiAgent-Platform, so code can
move between them without a licensing question, and held by the research
centre rather than an individual so that people moving on does not create a
reattribution problem.

Section 13 is why this is not merely administrative here. Unlike the GPL, the
AGPL treats network interaction as distribution, and this platform exposes both
a public inference API and a public management UI. Anyone reaching those
endpoints is entitled to the source of the running version, which makes it an
operational obligation: keep the deployed revision published and identifiable,
not just ship a LICENSE file. Recorded in `deployment.md` section 8.1 for that
reason.

### The public entrance, and the risks accepted with it

The original plan was Cloudflare Tunnel. It was dropped after checking two
things rather than assuming them.

`rcsl.online` is served by Gandi nameservers and the domain is actively
receiving mail through Gandi, so moving nameservers touches mail delivery on a
shared domain maintained by someone else. And Cloudflare's free tiers fix the
origin response timeout at 100 seconds, which streaming survives but a long
non-streaming completion does not.

So public traffic goes through the existing openresty proxy at NTNU instead. A
wildcard DNS record already points every subdomain there, so no DNS change is
needed; what is needed is that the proxy host joins the tailnet and forwards
two hostnames. Three consequences were accepted deliberately and are recorded
in `security.md` section 15 with the conditions that should trigger revisiting
them: inference traffic passes through a third party in plaintext, there is no
edge WAF or DDoS protection, and the country filter is bypassable by anyone
with a VPS in the right country.

The second of those is why the resource guardrails matter more here than they
would behind a CDN. They are not one layer of several; they are the only one.

### Architecture documents

Six documents, and the decisions behind them.

The one that shaped everything else: the gateway and the admin API must be
separate containers, because the isolation has to come from socket binding
rather than from a path rule in a reverse proxy that one typo could undo. That
in turn made the two admin entrances separate ASGI applications, since the
tailnet entrance trusts an identity header outright and sharing a socket with
the public entrance would let a forged header grant administrator access.

Authentication moved from OIDC to invitation-only local accounts with mandatory
TOTP, on the reasoning that the platform was already invitation-only in effect
(the `users` table gates access, not the identity provider), so the real choice
was who verifies the password. The trade is explicit: no external dependency
and no account an administrator did not create, in exchange for owning password
storage, reset, lockout and second-factor handling permanently. Mandatory TOTP
is what makes that trade acceptable.

A hardware constraint found while writing these, not while coding: model
runtimes cannot run in Docker on macOS, because containers there have no GPU
access. It contradicted the stated goal of keeping the host clean and was
non-negotiable, so the documents changed rather than the plan.

---

## Where things stand

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
Postgres 17.

What is still unverified, and by what: the **public entrance and nginx**, which
wait on the NTNU proxy administrator; the **unattended-recovery chain**, where
round one has passed three of four boots and **round two, the OS update, failed**
(runbook §1.1) — repaired, and the repair not yet through a boot; and **MLX**,
which has an adapter and no model registered against it.

**On the recovery chain specifically, because it is the item most likely to be
misread.** Four boots on 2026-07-26 found two independent faults, and the second
one is the reason the count above says "failed it" rather than "passed three
times".

The first: Docker Desktop drops the port forwards naming the tailnet address — it
restores containers before `tailscaled` has the address up, the bind fails, and the
daemon logs one warning and never retries. Nothing exits, so `restart:
unless-stopped` never fires; nine containers run, `healthy`, publishing nothing.

The second, on the 19:09 boot — which was round two, the macOS 26.5.2 update:
Docker Desktop did not restore the containers at all, and **nothing on the host was
responsible for the stack being up** — `docker compose up` appeared nowhere in
launchd, because Docker had always happened to do it. Worse, the reconciler swept
zero containers, found no dropped bindings, and exited 0 reporting an intact
platform.

`launchd/reconcile-port-bindings.sh` now covers both, and
`check-platform-health.sh` mails on a state change and did correctly catch the
second. **Neither repair path has been exercised by an actual reboot** — the
binding path has never once been triggered by a boot, and the bring-up path was
written after the boot that needed it. That is the whole point of the property, so
until round one is re-run and passes, the chain is repaired-but-unproven, not
proven.

### If you are picking this up cold

Read this section, then the 2026-07-26 entries above, then
[runbooks/first-deploy.md](./runbooks/first-deploy.md) §1.1. The single most
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

## What comes next

Four things are open as of the end of 2026-07-26, in the order they should be
picked up.

**1. Re-run the reboot test, and force a boot that loses the port-binding race.**
[runbooks/first-deploy.md](./runbooks/first-deploy.md) §1.1. Where it stands: round
one passed three of four boots (16:45 failed, 17:21 and 18:08 passed), and **round
two, the OS update, failed** — 19:09, Docker Desktop restored no containers and the
reconciler reported success on an empty platform. That was a new fault rather than
a recurrence, and it is not a round-one failure: the gate was correctly observed,
round two just tested something the three passes could not. Both defects are fixed;
neither fix has been through a boot.

Two of the six outcomes in §1.1 have never been produced by a boot, and each
proves a different repair path. `docker did not restore the stack; bringing it up`
→ `stack up: all expected services running` proves the bring-up path written after
the 19:09 failure. `OK: all bindings restored` proves the binding path, which four
boots have now failed to trigger because `tailscaled` won the race every time it
was a race at all. **A person must be at the machine.**

The second of those is no longer a matter of rebooting and hoping. The losing boots
are the ones that start without a netmap disk cache, and a boot that reads the
cache does not rewrite it — so **reboot twice in a row and watch the second one**,
which is the one that will have to wait for control before the address comes up.
The model has now predicted correctly once (19:09 read the cache and won by the
widest margin of the four), and by the same rule **the next boot is a slow one** —
so the next reboot is already the high-probability attempt at the binding path,
before any doubling up. If the margin stops alternating the way this predicts,
that is worth knowing too.

Round two no longer needs scheduling — 26.5.2 is installed — but it has to be
*passed*, which means re-running §1.1 in full on the machine as it now is. The two
settings checks that round two was written for (`autoLoginUser`, `pmset
autorestart`) both survived the update; what did not survive was something nobody
had listed, so after any future update the whole of §1.1 is the test, not those two
lines. Nothing should be concluded about the platform surviving a power cut until
both repair paths above have been walked by a real boot.

**2. Give the first administrator public-entrance credentials.** The account
bootstrapped from a tailnet identity carries no `password_hash` and no
`totp_secret` — the tailnet entrance does not need them. The public entrance
requires both, so as things stand nobody can sign in there once nginx exists, and
by then the reason will not be obvious. Fix from the Users page now; the runbook's
§7 has the step and the SQL that confirms it.

**3. Send the proxy administrator their four items.** A drafted request with the
real values is not in the repository (it names a person's mailbox and carries
setup detail); the content is [deployment.md](./architecture/deployment.md) §5
plus the runbook §8, and the tailnet is now ready for it — `tag:ntnu-proxy` will
apply, which it would not have before the ACL was in place. The shared secret goes
by a separate channel from the configuration. This unblocks the public entrance,
which is the largest unverified surface left.

**4. Then the roadmap.** Phase 2's remaining items are the knowledge base, prompt
templates, logging boundaries, full audit coverage, backups, and the `MetricsPort`
ingestion that now has a real number to be calibrated against (a loaded 7B model
measured 5.7 GB resident against 4.7 GB of weights, with `OLLAMA_KV_CACHE_TYPE=q8_0`
in the committed plist; without it the same model measured 6.6 GB).

Two smaller things worth not losing: the GeoLite2 database has no refresh
mechanism and nothing said so until today (`ROADMAP.md` Phase 3), and the
frontend test runner still covers logic units only — Playwright over the sign-in
and enrolment screens remains the deferred increment.

### Done: the first Mac Studio deploy

Carried out on 2026-07-26 and recorded in the dated entries above. The checklist
below is kept because it is still the shape of the work, and because everything
in it that has *not* been done is now visible by contrast: the proxy
administrator's four items and the §14 pre-launch checks are still outstanding,
and the runbook has gained the steps this deploy showed were missing from it.

- Install Ollama natively under launchd as a dedicated service account, bound
  to `127.0.0.1`.
- Ask the NTNU proxy administrator for four things, listed in `ROADMAP.md`:
  join the tailnet under `tag:ntnu-proxy`, add two nginx server blocks, issue
  Let's Encrypt certificates, and confirm no request-body logging.
- Populate `./secrets` from `secrets/README.md`: three distinct database URLs,
  the postgres password matching the owner URL, and real values for the rest.
- Confirm the account split holds against the live database, which nothing has
  exercised yet: `migrate` creates the two roles and their grants, each service
  connects as its own account, and the gateway's account is refused an INSERT
  into `api_keys`.
- Work through the pre-launch checklist in `security.md` section 14. Several
  items say to test rather than assume, and mean it: the forged
  `Tailscale-User-Login` case, the forged `X-Forwarded-For` case, and
  `AUTH_MODE=dev` refusing to boot under `ENV=production`.

### Phase 2 and beyond

Detail in `ROADMAP.md`. The parts that will need real design work rather than
implementation:

- **A second runtime adapter** (vLLM or MLX). Worth doing early even if unused,
  because it is the only real test of whether the hexagonal layering delivered
  what it was chosen for. If adding one requires touching a use case, the
  abstraction failed.
- **Multi-tenancy.** Currently single tenant, stated as such. The Phase 1
  schema was written not to preclude it, but adding `tenant_id` touches every
  repository and the filter has to be injected inside the adapter so a caller
  cannot forget it.
- **Prometheus and Grafana** are now built on the emission side (see the
  2026-07-25 entry). What remains is the ingestion half: a live free-memory
  figure feeding the memory budget, which needs the Mac Studio to produce a real
  one.
- **A second compute node**, which is the point of the node abstraction and
  will be the first time routing has more than one place to send anything.

### Open decisions

- **Whether to move `rcsl.online` to Cloudflare**, or register a separate cheap
  domain for the data plane. Either removes the accepted risk in `security.md`
  section 15.1, where inference traffic passes through a third-party machine in
  plaintext. Deferred, not settled.
- **Where the identity comes from.** No logo; the drawn one was rejected.
- **Whether the admin API should be reachable publicly at all.** It is designed
  for it and the entrance exists, but nothing depends on it yet, and closing it
  would remove an entire attack surface. Worth asking again once the tailnet
  entrance is in use and it is clear who actually cannot install Tailscale.

### Standing risks to revisit

`security.md` section 15 records four accepted risks with the conditions that
should trigger reconsidering them. The one most likely to change is 15.1: if
the platform starts handling personal or IRB-regulated data, plaintext
inference traffic through a third-party proxy stops being acceptable and the
Cloudflare question above becomes urgent rather than optional.
