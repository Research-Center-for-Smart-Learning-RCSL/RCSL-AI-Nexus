# What comes next

[← the progress log index](../PROGRESS.md)

> **A point-in-time snapshot, written 2026-07-26, kept for the record and not maintained.** The plan lives in [ROADMAP.md](../ROADMAP.md) and the control-by-control inventory in [security.md](../architecture/security.md) §13.0. Where this disagrees with either, or with a dated entry in the log, this is the one that is wrong.

Written at the end of 2026-07-26 as four open items, in the order they should be
picked up, and kept below rather than rewritten because the shape of the work is
still the record. **Where they stand as of 2026-08-05:**

| | State |
|---|---|
| **1.** Re-run the reboot test, force the binding race | **Closed 2026-07-26 that evening.** Both repair paths were exercised by real boots with injected faults (21:05:31 and 21:52:14). The item below predates those boots and describes them as still needed |
| **2.** First administrator's public-entrance credentials | **Closed 2026-08-02**, and marked so below |
| **3.** Send the proxy administrator their four items | **Sent 2026-08-03 and largely done**, then **partly reopened 2026-08-04 by the rename** to `llm`/`llmapi`. Still the only thing standing between this deployment and a public entrance |
| **4.** Then the roadmap | Superseded; the paragraph below is stale and corrected at the end of this section |

**The single most useful thing to read instead is the ROADMAP**, which is
maintained item by item, and the dated entries at the top of this file. This
section is history with a status column now, not a plan.

**1. Re-run the reboot test, and force a boot that loses the port-binding race.**
[runbooks/first-deploy.md](../runbooks/first-deploy.md) §1.1. Where it stands: round
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

**2. Give the first administrator public-entrance credentials. — Done
2026-08-02.** The account bootstrapped from a tailnet identity carried no
`password_hash` and no `totp_secret`; the public entrance requires both, so
nobody could have signed in there once nginx existed, and by then the reason
would not have been obvious. Closed through the Users page, and the login flow
itself was then driven with `curl` to prove the public entrance works before
nginx exists. See the 2026-08-02 entry at the top of this file.

**3. Send the proxy administrator their four items.** A drafted request with the
real values is not in the repository (it names a person's mailbox and carries
setup detail); the content is [deployment.md](../architecture/deployment.md) §5
plus the runbook §8, and the tailnet is now ready for it — `tag:ntnu-proxy` will
apply, which it would not have before the ACL was in place. The shared secret goes
by a separate channel from the configuration. This unblocks the public entrance,
which is the largest unverified surface left — though **the application half of
it stopped being unverified on 2026-08-02**, when its full login flow was driven
end to end without nginx. What these four items unblock is the network path to
that socket, not the socket's behaviour.

**4. Then the roadmap.** As written on 2026-07-26 this listed the knowledge base,
prompt templates, logging boundaries, full audit coverage, backups, and
`MetricsPort` ingestion. The knowledge base landed 2026-07-30 and the audit and
authorization sweeps 2026-08-02, so what is left of Phase 2 is **prompt template
management, the logging boundaries and expiring debug switch, encrypted backups
and a rehearsed restore, the `/api-docs` gaps recorded 2026-07-30, and the
`prompt_tokens` decision**. `MetricsPort` ingestion is half done via the residency
read-back and now has a real number to calibrate against (a loaded 7B model
measured 5.7 GB resident against 4.7 GB of weights, with `OLLAMA_KV_CACHE_TYPE=q8_0`
in the committed plist; without it the same model measured 6.6 GB).

Two smaller things worth not losing: the GeoLite2 refresh **script** now exists
(`launchd/refresh-geolite2.sh`, written 2026-07-30) but **its plist is not
installed**, because `secrets/maxmind_license_key` has not been placed — so the
country database is still ageing with nothing to stop it, which is the same
outcome the missing mechanism had. And the frontend test runner still covers
logic units only; Playwright over the sign-in and enrolment screens remains the
deferred increment, now with a live enrolled account to drive it against.

---

**Corrected 2026-08-05.** The four paragraphs above are the 2026-07-26 text and
three of them have since become false; they are kept because the reasoning is
still worth reading, and contradicted here rather than edited in place so the
drift is visible instead of erased.

- **Phase 2 is not "prompt templates, logging boundaries, backups, `/api-docs`
  gaps and `prompt_tokens`".** All but backups are done: `/api-docs` on
  2026-08-03, `prompt_tokens` on 2026-08-04, the expiring debug switch on both
  credentials and prompt template management on 2026-08-05. What is left is
  **encrypted backups with a rehearsed restore**, **Storybook**, and the
  *logging boundaries* half of §9.2 — full prompt/completion logging, which the
  switch could now gate and nothing yet writes.
- **The GeoLite2 plist is installed.** It went in on 2026-08-03 with the licence
  key, was proven by a hand run before the daemon was loaded, and fires
  Wednesdays at 05:30. The database is no longer ageing unattended.
- **Playwright is still the deferred increment**, and this is the one that
  stayed true. It is now the last unchecked Phase 1 frontend item, listed under
  Phase 3.

The rest of the roadmap's state lives in [ROADMAP.md](../ROADMAP.md), which is
maintained per item and is the file to trust for "what is left".

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
- **Multi-tenancy.** Done; see the 2026-07-25 entry. The knowledge base, its
  main consumer, now plugs into that boundary and enforces it in three more
  places (the two tables, the document path, and the Qdrant collection name).
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
- **How long an audit entry and a usage record are kept, and who may delete
  one.** Both tables are append-only with nothing that prunes them, which is the
  right default and not a policy. Neither is near a capacity problem — 160 kB
  and 120 kB after nine days — so this is wanted before somebody asks the
  platform to forget something, not because of disk. The answer constrains the
  backup story too, and `usage_records` is what quotas are measured against, so
  a retention window shorter than the longest quota period would be a
  correctness bug rather than a cleanup. See the 2026-08-04 growth audit.
- **Where the identity comes from.** No logo; the drawn one was rejected.
- **Whether the admin API should be reachable publicly at all.** It is designed
  for it and the entrance exists, but nothing depends on it yet, and closing it
  would remove an entire attack surface. Worth asking again once the tailnet
  entrance is in use and it is clear who actually cannot install Tailscale.

- **Whether anything should be done about memory headroom. — OPEN, raised
  2026-08-05, leading candidate: nothing.** Free memory swings between ~12 GB
  and ~37 GB of 64 depending on whether the node is serving; inference wires
  the three permanently-resident models in about a second and idle releases
  them back to clean file-backed pages the OS may evict and re-read from SSD.
  The SSD-for-RAM trade this was opened to consider is therefore **already
  happening**, at page granularity, without a setting. **q4 quantisation** is
  the one real alternative (≈18 GB back, trading quality rather than speed);
  **a keep-alive duration** is the coarse version of what the OS already does.
  Evidence, and the confident wrong inference that preceded it, are in the
  2026-08-05 entry at the top of this file.

  **Measured further 2026-08-07, and every result points the same way.** The
  wiring tail is **19 minutes**, two runs agreeing within three seconds. The
  trigger is a single request of any size — a 0.9-second, two-token reply wires
  the same 38.5 GB a real workload does. The release is a change of page status
  rather than a reclaim, performed by the OS and not by Ollama. And the machine
  spent those nineteen minutes at 0.1–0.7 GB free with **swap at 0 bytes and
  nothing degrading**, twice. Usage is per session rather than steady (152 of
  181 real request gaps are under nineteen minutes), so ~12 GB is the whole of
  a working session and ~37 GB is between them. **The binding constraint is
  neither figure**: the static budget allows 51.2 GiB against 41.33 loaded, so
  9.87 GiB is what decides whether another model may be loaded. Remaining
  measurements: eviction under real pressure (a decision, since it needs a
  deliberate allocation on a serving machine), q4's quality here, and a
  full-context request. The "unexplained 3 GB" is closed — GiB against decimal
  GB, with the budget's units consistent.
  **Nothing has been changed on the deployment.**

### Standing risks to revisit

`security.md` section 15 records four accepted risks with the conditions that
should trigger reconsidering them. The one most likely to change is 15.1: if
the platform starts handling personal or IRB-regulated data, plaintext
inference traffic through a third-party proxy stops being acceptable and the
Cloudflare question above becomes urgent rather than optional.
