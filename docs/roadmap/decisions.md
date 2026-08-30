# Decisions

[← the roadmap](../ROADMAP.md)

No open decisions block Phase 1.

**Open — raised 2026-08-05, nothing changed on the deployment:**

- **Memory headroom, which turned out to be a question about *when* it is measured.**
  Free memory on this node swings between ~12 GB and ~37 GB of 64: inference
  wires the three permanently-resident models (44.4 GB) within a second, and
  after a long enough idle they revert to clean file-backed pages of the
  mmapped blob that the OS may evict and re-read from SSD. Measured both ends
  with nothing unloaded in between. **So the SSD-for-RAM trade this was opened
  to consider is already happening**, at page granularity, without a setting.
  What is left to decide is whether anything is worth doing at all — the
  leading candidate is **nothing**, since swap is at 0 bytes and the platform
  is not degrading; **q4 quantisation** is the one real alternative (≈18 GB
  back, trades quality not speed, probably faster since bandwidth is the
  bottleneck); **a keep-alive duration** is now the weakest, being the coarse
  version of what the OS already does. **An earlier version of this item asserted
  the weights were permanently unreclaimable; it was labelled unproven, checked
  because of the label, and was wrong.** Evidence and the failed inference in
  [PROGRESS.md](../PROGRESS.md) 2026-08-05; guardrail context in
  [security.md](../architecture/security.md) §4.3.

  **Measured 2026-08-07, and it strengthens "nothing".** The wiring tail is
  **19 minutes** — two runs put the release inside (1139, 1151] seconds,
  agreeing within three seconds. The trigger is a *single request of any size*:
  a 0.9-second, two-token generation wired 38.5 GB. The release is a change of
  page status rather than a reclaim, and the OS does it, not Ollama. Across
  both runs the machine spent nineteen minutes at 0.1–0.7 GB free with **swap
  at 0 bytes and nothing degrading**. And the shape is per session rather than
  steady: 152 of 181 real request gaps are under nineteen minutes, so a working
  session sits at ~12 GB throughout and the idle machine returns to ~37 GB.
  **The number that actually constrains the deployment is neither** — the
  static budget allows `64 GiB × 0.8 = 51.2` against 41.33 observed as loaded,
  so 9.87 GiB is what decides whether a fourth model may be loaded, and no
  finding here touches it. Remaining open measurements: whether eviction occurs
  under real pressure (a decision, not a measurement — it needs a deliberate
  allocation on a serving machine), q4's quality here, and whether headroom
  survives a full-context request. The "unexplained 3 GB" is closed: it was
  GiB against decimal GB, and the budget's units are consistent

  **Priced 2026-08-13, and the pricing reorders the question.** Extending the
  372 GB/s bandwidth model with the SSD's ~7 GB/s gives a ratio of 53x, and the
  sensitivity is the finding: **1% of per-token bytes coming off SSD costs a
  third of the throughput, 10% costs a factor of six**. So "spend SSD for RAM"
  is a cliff rather than a slope, it works only for MoE models with a small
  active fraction, and only while the model still nearly fits. Roughly 1.2x
  oversubscription of the 51.2 GiB budget is survivable and 2x is not. The
  larger finding is that this deployment does not need the trade to get the
  gain: `gemma4:31b-it-q8_0` is **dense**, so it reads all 31.4 GiB per token
  for 13.6 tok/s, while a much larger sparse MoE reads a few GB per token and
  lands faster. Moving from dense to sparse is better on both axes at once.
  Prompt evaluation is compute-bound (q4 and q8 measured identical), so a
  low-active-parameter model should improve the 556-second worst case rather
  than threaten it. **The prediction held and the figure did not**: 556 s was
  65,536 tokens at the dense model's 117.9 tok/s, and at the 711-730 tok/s
  `qwen36-35b-a3b-q8` measured on 2026-08-17 today's 122,880-token ceiling costs
  173 s. Full derivation, the two blockers, and what is still
  unmeasured in [PROGRESS.md](../PROGRESS.md) 2026-08-13.

  **Closed 2026-08-14 by measuring both halves, and the streaming half of the
  paragraph above is wrong.** The SSD is not one number: 7.31 GB/s with eight
  parallel readers at 1 MiB, but **0.89 GB/s through the mmap page faults Ollama
  actually uses**, a 21x spread where the applicable row is a property of the
  runtime rather than the disk. So the ratio for this deployment is 418x rather
  than 53x, and **"roughly 1.2x oversubscription is survivable" is wrong**: at a
  measured 1.29x, on the same weights at two precisions, generation fell 14.6x
  and **prompt evaluation fell 150x** (1528.8 to 10.2 tok/s), putting a full
  context 10.7x past `request_timeout_seconds`. Ollama does not stream experts at
  all -- it splits layers 27%/73% CPU/GPU, which frees no memory on a unified
  architecture. **No oversubscription is viable through this runtime.** What
  survives, and understates itself, is dense-to-sparse: `qwen3.6:35b-a3b-q8_0`
  fits in 37 GB and measures 5.1x the generation and 7.7x the prompt evaluation
  of what is deployed, needing no SSD whatsoever. See
  [PROGRESS.md](../PROGRESS.md) 2026-08-14.

- **Whether a sparse model exists in the size class this machine can nearly
  hold, and whether it is any better.** Raised 2026-08-13 by the entry above,
  and it is the question that would actually change what this platform serves.
  Two things gate it and neither is a download. `assert_can_load` refuses
  anything past 51.2 GiB, and that guardrail assumes resident means wired means
  unavailable, which 2026-08-05 disproved on this machine (40.6 GB wired to
  2.3 GB with nothing unloaded); a deliberately oversubscribed model needs
  `MemoryBudgetService` to separate what must stay resident from what may be
  evictable file-backed pages, which is a [security.md](../architecture/security.md)
  §4.3 change rather than a constant. And the KV cache at `MAX_CONTEXT_LENGTH`
  competes with the experts for the same memory, so the context ceiling and the
  model choice are one decision. Capability is separate from arithmetic: the
  ten-rung harness already has no resolution at the level where q4 and q8
  differ, so it will not settle this either.

  **Half-answered 2026-08-14, and the half that matters is still open.** The
  arithmetic question is settled and the answer needed no oversubscription:
  `qwen3.6:35b-a3b-q8_0` is 35B total on 3B active, fits in 37 GB, and measures
  5.1x the generation and 7.7x the prompt evaluation of `gemma4:31b-it-q8_0`.
  `assert_can_load` never comes into it, so the §4.3 change is no longer on this
  path. **Whether it is any better is still unanswered, and now measured to be
  unanswered**: scored against `gemma4:31b-it-q8_0` and `qwen3.6:27b-q8_0` on
  twelve programmatically-checked tasks over three interleaved rounds, the three
  landed at 92%, 97% and 94%, with ten of the twelve saturated. Parity at this
  difficulty, three months of model generation apart -- and the same sentence
  2026-08-07 had to write about q4 against q8. The switch is worth making on the
  wall clock alone -- identical scores in a third of the time -- but it should
  not be made on a claim of being smarter, because nothing here demonstrates one.

  **Answered 2026-08-15, and the answer is that the incumbent is the better
  model and should be replaced anyway.** The **eighteen**-task set in
  [model-evaluation.md](../model-evaluation.md) — this line said sixteen until
  2026-08-18, four paragraphs above one that says eighteen and against a
  `scripts/model-eval/tasks.py` carrying eighteen task ids — ran against all
  three candidates,
  three interleaved rounds, 162 samples of which 159 scored — 189 written, with
  the `repair` phase superseding the three tasks it re-ran; the 280 rows in
  `results.jsonl` also count the two calibration phases, which ran against the
  incumbent alone — harness committed at
  [`scripts/model-eval/`](../../scripts/model-eval/):

  | | score | gen tok/s at depth ~710 | wall clock per round |
  |---|---:|---:|---:|
  | `gemma4:31b-it-q8_0` | **94.4%** | 13.6 | 551-615 s |
  | `qwen3.6:35b-a3b-q8_0` | 89.8% | **67.5** | **246-285 s** |
  | `qwen3.6:27b-q8_0` | 87.5% | 15.4 | 907-1060 s |

  Unlike 2026-08-14's 92/97/94 this separates them and the order held every
  round; `gemma4` is never beaten on a single task. So the switch to
  `35b-a3b` costs 4.6 points of capability and buys a round in 45% of the wall
  clock. **For the `code` capability that trade is worth making** — an agent
  loop pays the latency once per turn and the deficit sits in four tasks — and
  the sentence this file has been carrying since 2026-08-14 stands with evidence
  behind it now rather than an absence: it is worth switching on the wall clock,
  and it is not a smarter model. `qwen3.6:27b-q8_0` is out on both axes.

  **What the number is worth.** Thirteen of the eighteen tasks carry no signal
  across the candidates once `repair` supersedes what it re-ran — twelve every
  candidate passes every time, plus `insufficient_data`, which every candidate
  fails every time — so the 6.9-point spread rests on three of them:
  `retry_deadline`, `cache_decorator` and the `ini_parse` anchor. (Against the
  `full` phase alone it reads eleven and four, because `range_sum_updates` only
  saturates after the re-run, and the group A pair is `undecided` rather than
  separating.) The instrument is thin even where its verdict is stable. The set never reached its
  own 40-70% calibration band, in two attempts. And it says nothing about
  whether the code is any good, which remains the open item below.

  **Model-independent and unrelated to this decision: every candidate fabricated
  rather than refusing**, nine samples out of nine, on the one task whose right
  answer is "the data does not determine this". That belongs to what the
  platform tells a caller, not to which model serves them ([PROGRESS.md](../PROGRESS.md)
  2026-08-15).

Settled:

- Backend structure: full hexagonal architecture ([backend.md](../architecture/backend.md))
- Frontend component library: shadcn/ui ([frontend.md](../architecture/frontend.md))
- Gateway and admin split into separate containers; the admin entrances are two more ([security.md](../architecture/security.md) §1)
- Management authentication: Tailscale identity on the tailnet; invitation-only local accounts with mandatory TOTP on the public entrance. No external identity provider, and no account exists that an administrator did not create ([security.md](../architecture/security.md) §5)
- Public entrance: the existing openresty proxy plus the `*.rcsl.online` wildcard ([deployment.md](../architecture/deployment.md))
- Source restriction: application-layer country filter, Taiwan and Australia ([security.md](../architecture/security.md) §4.1)
- Gateway exposes an OpenAI-compatible API
- First capability: `chat`. First runtime: Ollama, native on the host
- Chat UI is served by the admin API, not the public gateway ([security.md](../architecture/security.md) §5.2)
- Single tenant through Phase 1 ([ARCHITECTURE.md](../ARCHITECTURE.md) §2.8)
- Images built on the Mac Studio; migrations as a one-shot service ([deployment.md](../architecture/deployment.md) §9)
- Accepted risks recorded in [security.md](../architecture/security.md) §15
